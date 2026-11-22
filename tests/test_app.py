import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["CACHE_DB"] = tempfile.mktemp(suffix=".sqlite3")
import app as provider


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.client = provider.app.test_client()

    def test_language_normalization_without_duplicate_suffix(self):
        self.assertEqual(provider.normalize_language("fra"), "fra")
        self.assertEqual(provider.normalize_language("fr-FR"), "fra")
        self.assertEqual(provider.normalize_language("eng"), "eng")
        self.assertEqual(provider.normalize_language("en-US"), "eng")

    def test_forced_language_ignores_plex_header(self):
        with patch.dict(os.environ, {"TVDB_FORCE_LANGUAGE": "true"}):
            with provider.app.test_request_context(headers={"X-Plex-Language": "en-US"}):
                self.assertEqual(provider.language(), "fra")

    def test_unforced_language_uses_plex_header(self):
        with patch.dict(os.environ, {"TVDB_FORCE_LANGUAGE": "false"}):
            with provider.app.test_request_context(headers={"X-Plex-Language": "en-US"}):
                self.assertEqual(provider.language(), "eng")

    def test_season_artwork_prefers_french_poster(self):
        with provider.app.test_request_context():
            src = {"name": "Season 1", "artwork": [
                {"type": 7, "language": "eng", "image": "https://example.org/en.jpg", "score": 99},
                {"type": 7, "language": "fra", "image": "https://example.org/fr.jpg", "score": 1},
                {"type": 8, "language": "fra", "image": "https://example.org/bg.jpg"},
                {"type": 6, "language": "fra", "image": "https://example.org/banner.jpg"}]}
            item = provider.season_record(44, 1, "Example", "https://example.org/show.jpg", src)
            self.assertEqual(item["thumb"], "https://example.org/fr.jpg")
            self.assertEqual(item["art"], "https://example.org/bg.jpg")
            self.assertNotIn("https://example.org/banner.jpg",
                             [i["url"] for i in item["Image"]])

    def test_season_type_selection(self):
        src = {"seasons": [{"id": 10, "number": 1, "type": {"type": "official"}, "image": "official.jpg"},
                           {"id": 20, "number": 1, "type": {"type": "dvd"}, "image": "dvd.jpg"}]}
        self.assertEqual(provider.season_source(src, 1, "default")["id"], 10)
        self.assertEqual(provider.season_source(src, 1, "dvd")["id"], 20)
        self.assertIsNone(provider.season_source(src, 1, "absolute"))

    @patch.object(provider, "tvdb")
    def test_extended_season_artwork(self, mock_tvdb):
        series = {"id": 44, "name": "Test", "seasons": [
            {"id": 123, "number": 1, "type": {"type": "official"}}]}
        mock_tvdb.return_value = {"data": {"id": 123, "name": "Saison 1",
              "artwork": [{"type": 7, "language": "fra", "image": "https://example.org/s1.jpg"}]}}
        with provider.app.test_request_context():
            item = provider.season_record(44, 1, "Test", None, provider.season_details(series, 1))
        self.assertEqual(item["thumb"], "https://example.org/s1.jpg")
        self.assertIn("/seasons/123/extended", mock_tvdb.call_args.args[0])

    @patch.object(provider, "show")
    @patch.object(provider, "tvdb")
    def test_automatic_match_prefers_year(self, mock_tvdb, mock_show):
        mock_tvdb.return_value = {"data": [
            {"id": "11"}, {"id": "22"}]}
        mock_show.side_effect = lambda ident: {"id": ident, "name": "Same Title",
                                    "firstAired": "2020-01-01" if ident == 11 else "2026-01-01"}
        resp = self.client.post("/tv/library/metadata/matches",
                                json={"type": 2, "title": "Same Title", "year": 2026})
        self.assertEqual(resp.status_code, 200)
        items = resp.json["MediaContainer"]["Metadata"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["ratingKey"], "tvdb-show-22")

    def test_health(self):
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_provider_manifest(self):
        result = self.client.get("/tv")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["MediaProvider"]["Feature"][0]["key"], "/library/metadata")

    def test_bad_rating_key(self):
        self.assertEqual(self.client.get("/tv/library/metadata/invalid").status_code, 400)

    @patch.object(provider, "tvdb")
    def test_series_french_translation_dedicated_endpoint(self, mock_tvdb):
        def api(path, params=None):
            if path.endswith("/extended"):
                return {"data": {"id": 99, "name": "English", "overview": "English overview"}}
            if path.endswith("/translations/fra"):
                return {"data": {"name": "Titre francais", "overview": "Resume en francais"}}
            raise AssertionError(path)
        mock_tvdb.side_effect = api
        with provider.app.test_request_context(headers={"X-Plex-Language": "fr-FR"}):
            item = provider.show_record(provider.show(99))
        self.assertEqual(item["title"], "Titre francais")
        self.assertEqual(item["summary"], "Resume en francais")

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

    @patch.object(provider, "show")
    @patch.object(provider, "episodes")
    def test_season_children(self, mock_episodes, mock_show):
        mock_show.return_value = {"id": 1, "name": "Test Show", "seasons": []}
        mock_episodes.return_value = [
            {"id": 1, "seasonNumber": 1, "number": 2, "name": "Second"},
            {"id": 2, "seasonNumber": 2, "number": 1, "name": "First"}
        ]
        response = self.client.get("/tv/library/metadata/tvdb-show-1/children")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([x["index"] for x in response.json["MediaContainer"]["Metadata"]], [1, 2])


if __name__ == "__main__":
    unittest.main()
