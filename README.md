# Plex Local TVDB

Standalone **Plex Custom Metadata Provider**, hosted on a Synology NAS and queried over LAN by Plex Media Server on an NVIDIA Shield Pro. Uses TheTVDB API v4 **with your own authorized API key/PIN**.

**Release candidate v0.2.0** — series, seasons, episodes, French metadata, season-specific artwork, year-aware matching, SQLite cache and a Git-free Synology updater. Basic functionality has been exercised with PMS 1.43.5.11079, but this release **has not yet been tested end-to-end for DVD/Absolute/anime-specific orders on the Shield**.

TheTVDB is the metadata source, not a bypass of TheTVDB's licensing. This product is not endorsed by TheTVDB.

## Requirements

- Plex Media Server 1.43.0+ with Custom Metadata Providers
- NAS with Docker Compose, `wget` and `curl` (no Git/unzip/Python needed on NAS)
- TheTVDB API v4 credentials (key, optional PIN)
- LAN access from Plex to NAS TCP port (here 3010)

## Initial NAS installation (Synology DSM)

Download main ZIP from GitHub using a browser, extract on your PC and upload the files to `/volume1/docker/plex-local-tvdb/` with File Station. Or follow the existing [Docker instructions](https://github.com/SepuLeVrai/plex-local-tvdb).

In the project directory:
```sh
sudo cp .env.example .env
sudo mkdir -p data
sudo chown -R 10001:10001 data
# edit .env with the authorized API key/PIN and PORT=3010
sudo docker compose up -d --build
sudo docker compose ps
curl -fsS http://127.0.0.1:3010/health
```

Configuration:
```ini
TVDB_API_KEY=YOUR_OWN_KEY
TVDB_PIN=YOUR_PIN_IF_REQUIRED
TVDB_LANGUAGE=fra
TVDB_FORCE_LANGUAGE=true
TVDB_ORDER=default
CACHE_TTL_SECONDS=86400
CACHE_DB=/data/cache.sqlite3
PORT=3010
BIND_ADDRESS=0.0.0.0
```
Keep `.env` private. Do not publish 3010 to the internet. Constrain access with Synology firewall rules.

### Update without Git/unzip

Once `update-synology.sh` is present:
```sh
cd /volume1/docker/plex-local-tvdb
sudo sh update-synology.sh
```
The script resolves the latest commit SHA via GitHub API, downloads a pinned ZIP, uses disposable Python Docker for extraction, backs up source files in `.update-backups/`, rebuilds, health-checks and restores previous source files if deployment/health-check fails. **It never overwrites `.env` or `data/`.** A successful `/health` proves the HTTP service is up, not that every TVDB lookup will work.

If the script is not present yet, download it from a **pinned commit** rather than the potentially stale `raw/main` endpoint.

## Plex configuration

In Plex Web → Settings → Metadata Agents, add provider URL `http://NAS_IP:3010/tv`, then create an Agent with this provider as Primary Provider. Select that Agent in **Library → Edit → Advanced → Agent**.

Do not confuse the library's **Episode ordering** field with the custom metadata provider. The former may still show TMDB and TVDB choices independent of your custom agent.

## Verified smoke tests

```sh
curl -fsS http://127.0.0.1:3010/health
curl -fsS http://127.0.0.1:3010/tv
curl -fsS "http://127.0.0.1:3010/tv/library/metadata/tvdb-show-81189/images"
curl -fsS "http://127.0.0.1:3010/tv/library/metadata/tvdb-season-81189-1/images"
curl -fsS "http://127.0.0.1:3010/tv/library/metadata/tvdb-season-81189-1/children"
```
The season-images endpoint should return a `coverPoster` pointing at a **season-level** image when TVDB has one. If TVDB has none, fall back to series artwork. Refresh a **single** Plex show after updating.

## Episode ordering / anime

`TVDB_ORDER` selects the globally configured TVDB order for this provider instance:
- `default` / `official`: aired order (recommended for initial production trial)
- `dvd`: DVD order **when TVDB supplies one**
- `absolute`: absolute order **when TVDB supplies one**

**Caution:** DVD and Absolute support has not been field-tested with Plex's `episodeOrdering` / `SeasonType` UI. The provider currently does **not** advertise alternative orders per individual series; do not assume changing Plex's “Episode ordering” setting will change `TVDB_ORDER`. Do not migrate an anime library using custom numbering until you verify at least one representative series end-to-end. For a library with mixed orders, this version is not a drop-in replacement.

## Safe migration to production

1. Back up the Plex server's metadata/database first; back up the NAS provider directory including `.env` and `data/`.
2. Keep the existing agent selected for both production libraries.
3. Test three cases in a disposable library: standard series, multi-season show with individual posters, and an anime with specials and/or absolute/DVD numbering.
4. Test exact file-to-episode alignment, watched state, multi-episode files, dates, language, posters, special episodes. Take screenshots or list mismatches.
5. Change **only the Series library**, initially one show, refresh, inspect. Do not bulk “Fix Match” or refresh everything during initial verification.
6. Only after stable results decide on anime; keep a rollback path and a recent Plex database backup.
7. Switching back to the previous agent does not necessarily restore all previous matches/watched metadata. Restore from the Plex backup if needed.

## Known boundaries

- Season-specific artworks come from `/seasons/{id}/extended`; missing season posters fall back to series poster. The initial season child list can use TVDB series-level season image; full season artwork is available by querying the season itself.
- Artwork is prioritized French, then language-neutral, then English.
- The API doesn't synthesize translations missing from TheTVDB.
- Matching is title/year aware; obscure aliases and ambiguous remakes still need review.
- Alternate episode ordering and full anime behavior are not yet end-to-end validated on Plex Shield. Ratings, complete cast/crew and all metadata subfields are not yet implemented.
- Current API cache has a fixed TTL; rate limits and upstream availability still apply.

## Tests and license

```sh
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

GitHub Actions runs unit tests and Docker build. API credentials are not included.

References: [Plex developer docs](https://developer.plex.tv/pms/), [TheTVDB v4 docs](https://thetvdb.github.io/v4-api/).
