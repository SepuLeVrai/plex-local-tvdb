# Plex Local TVDB

**Experimental v0.1.0** — standalone Plex Custom Metadata Provider using TheTVDB v4, designed for a Synology DS918+ Docker host and a separate Plex Media Server (including NVIDIA Shield). No Plex plugin, no direct modification of your Plex database.

> This product uses the TVDB API but is not endorsed or certified by TheTVDB.com. You must supply credentials granting authorized API access. This is not a bypass of TVDB authentication or licensing.

## Prerequisites

- Plex Media Server **1.43.0+** (tested target: 1.43.5.11079; integration not yet field-tested)
- Docker / Synology Container Manager, Compose support
- TheTVDB API key (and subscriber PIN where required)
- NAS and Plex host mutually reachable over LAN

## Install on Synology

```sh
git clone https://github.com/SepuLeVrai/plex-local-tvdb.git
cd plex-local-tvdb
cp .env.example .env
mkdir -p data
sudo chown -R 10001:10001 data
# edit .env with TVDB_API_KEY and optionally TVDB_PIN
docker compose up -d --build
docker compose ps
curl http://NAS_IP:3000/health
curl http://NAS_IP:3000/tv
```

For this development PR, checkout `feat/docker-tvdb-provider` before starting. Synology users may also build the project through Container Manager.

`/health` does not contact TheTVDB; a true lookup requires valid credentials. Keep `.env` private; the API key is never sent to Plex.

## Configure Plex (Shield PMS 1.43.5.11079)

1. Open **Plex Web → Settings → Metadata Agents → Add Provider**.
2. Enter `http://NAS_IP:3000/tv` (use your NAS LAN IP, **not localhost**).
3. Create an agent with **Plex Local TVDB** as its primary provider; optionally add Plex Local Media.
4. **Create a separate test TV library** first and choose that agent in Advanced settings.
5. Test one series, including episode mapping, French text and special episodes. Do **not** rematch or refresh your full existing library until verified.

The provider listens on port 3000 by default. Restrict access to the local network using the Synology firewall. Do not forward port 3000 to the Internet.

## Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `TVDB_API_KEY` | empty | Mandatory |
| `TVDB_PIN` | empty | For subscriber-based API credentials |
| `TVDB_LANGUAGE` | `fra` | French preferred; Plex language headers override |
| `TVDB_ORDER` | `default` | TheTVDB order URL slug; test before using alternative orders |
| `CACHE_TTL_SECONDS` | `86400` | SQLite-backed API response cache |
| `PORT` | `3000` | NAS published port |
| `BIND_ADDRESS` | `0.0.0.0` | Bind to a particular NAS interface if desired |

## Current limitations

- **Prototype, not production-ready**: no real TheTVDB credentials or live Shield access were available for end-to-end validation.
- Basic series/season/episode matching and images implemented; advanced artwork, cast, translations, DVD/absolute order mappings and resilient matching still need integration work.
- TheTVDB search and episode payload formats can vary; verify against actual response fixtures.
- Default episode order only is expected to be reliable initially.
- Do not treat a green health check as proof of Plex metadata compatibility.

## Development

```sh
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
CACHE_DB=/tmp/plex-tvdb-test.sqlite3 python -m unittest discover -s tests -v
```

## References

- [Plex custom provider announcement](https://forums.plex.tv/t/announcement-custom-metadata-providers/934384/)
- [Plex official provider reference implementation](https://github.com/plexinc/tmdb-example-provider)
- [TheTVDB API v4](https://thetvdb.github.io/v4-api/)
- [Prior community implementation](https://github.com/Drewpeifer/plex-meta-tvdb) (archived, research only)
