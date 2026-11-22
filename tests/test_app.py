import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["CACHE_DB"] = tempfile.mktemp(suffix=".sqlite3")
import app as provider


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.client = provider.app.test_client()

    def test_health(self):
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_provider_manifest(self):
        result = self.client.get("/tv")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["MediaProvider"]["Feature"][0]["key"], "/library/metadata")

    def test_bad_rating_key(self):
        self.assertEqual(self.client.get("/tv/library/metadata/invalid").status_code, 400)

    def test_plex_artwork_types(self):
        series = {"id": 44, "name": "Demo", "image": "https://example.org/poster.jpg",
                  "artworks": [{"type": 3, "image": "https://example.org/background.jpg"}]}
        item = provider.show_record(series)
        self.assertEqual(item["thumb"], "https://example.org/poster.jpg")
        self.assertEqual(item["art"], "https://example.org/background.jpg")
        self.assertEqual({x["type"] for x in item["Image"]}, {"coverPoster", "background"})

    @patch.object(provider, "tvdb")
    def test_episode_list_uses_french_endpoint(self, mock_tvdb):
        mock_tvdb.return_value = {"data": {"episodes": [
            {"id": 9, "seasonNumber": 1, "number": 1, "name": "Pilote"}]},
            "links": {"next": None}}
        with provider.app.test_request_context(headers={"X-Plex-Language": "fr-FR"}):
            items = provider.episodes(44)
        self.assertEqual(items[0]["name"], "Pilote")
        self.assertIn("/fra", mock_tvdb.call_args.args[0])

    def test_episode_snapshot(self):
        item = provider.episode_record(44, {"seasonNumber": 1, "number": 1,
                                            "name": "Pilote", "image": "https://example.org/still.jpg"}, "Demo")
        self.assertEqual(item["Image"][0]["type"], "snapshot")
        self.assertEqual(item["grandparentTitle"], "Demo")

    @patch.object(provider, "show")
    def test_show_metadata(self, mock_show):
        mock_show.return_value = {"id": 123, "name": "Example", "firstAired": "2020-01-01"}
        response = self.client.get("/tv/library/metadata/tvdb-show-123")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["MediaContainer"]["Metadata"][0]["title"], "Example")

    @patch.object(provider, "episodes")
    def test_season_children(self, mock_episodes):
        mock_episodes.return_value = [
            {"id": 1, "seasonNumber": 1, "number": 2, "name": "Second"},
            {"id": 2, "seasonNumber": 2, "number": 1, "name": "First"}
        ]
        response = self.client.get("/tv/library/metadata/tvdb-show-1/children")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([x["index"] for x in response.json["MediaContainer"]["Metadata"]], [1, 2])


if __name__ == "__main__":
    unittest.main()
