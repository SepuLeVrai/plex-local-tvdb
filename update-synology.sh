#!/bin/sh
# Synology DSM updater — no Git, unzip or Python required on the NAS.
# Requires Docker, Docker Compose, wget and a writable project directory.
set -eu
cd "$(dirname "$0")"
PROJECT=$(pwd)
WORK="$PROJECT/.update-work"
BACKUPS="$PROJECT/.update-backups"
mkdir -p "$WORK" "$BACKUPS"
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="$BACKUPS/$STAMP"
mkdir -p "$BACKUP"
echo "[1/6] Resolving main SHA through GitHub API"
wget -q -O "$WORK/commit.json" "https://api.github.com/repos/SepuLeVrai/plex-local-tvdb/commits/main"
SHA=$(sudo docker run --rm -v "$WORK:/work:ro" python:3.12-slim python -c "import json; print(json.load(open('/work/commit.json'))['sha'])")
case "$SHA" in
  *[!0-9a-f]*|'') echo "Invalid GitHub SHA"; exit 1;;
esac
echo "GitHub commit: $SHA"
echo "[2/6] Downloading pinned archive"
wget -q -O "$WORK/source.zip" "https://codeload.github.com/SepuLeVrai/plex-local-tvdb/zip/$SHA"
echo "[3/6] Extracting with temporary Python container"
sudo docker run --rm -v "$WORK:/work" python:3.12-slim python -c "
import os, zipfile
archive=zipfile.ZipFile('/work/source.zip')
prefix='plex-local-tvdb-' + '$SHA' + '/'
names=['app.py','Dockerfile','requirements.txt','compose.yaml','update-synology.sh']
for name in names:
    contents=archive.read(prefix+name)
    with open('/work/'+name,'wb') as out: out.write(contents)
"
echo "[4/6] Saving rollback files"
for file in app.py Dockerfile requirements.txt compose.yaml update-synology.sh; do
  [ ! -f "$file" ] || cp "$file" "$BACKUP/$file"
done
echo "[5/6] Deploying source and rebuilding"
for file in app.py Dockerfile requirements.txt compose.yaml update-synology.sh; do
  cp "$WORK/$file" "$file"
done
chmod +x update-synology.sh
if ! sudo docker compose config -q || ! sudo docker compose up -d --build --force-recreate; then
  echo "Deployment failed; restoring previous files"
  for file in app.py Dockerfile requirements.txt compose.yaml update-synology.sh; do
    [ ! -f "$BACKUP/$file" ] || cp "$BACKUP/$file" "$file"
  done
  sudo docker compose up -d --build --force-recreate || true
  exit 1
fi
echo "[6/6] Health-checking"
PORT=$(sed -n 's/^PORT=//p' .env | tail -n 1)
[ -n "$PORT" ] || PORT=3000
TRIES=0
until curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; do
  TRIES=$((TRIES+1))
  if [ "$TRIES" -ge 12 ]; then
    echo "Health check failed; restoring files"
    for file in app.py Dockerfile requirements.txt compose.yaml update-synology.sh; do
      [ ! -f "$BACKUP/$file" ] || cp "$BACKUP/$file" "$file"
    done
    sudo docker compose up -d --build --force-recreate || true
    exit 1
  fi
  sleep 3
done
echo "OK - Plex Local TVDB deployed from $SHA (port $PORT)"
echo "Rollback source: $BACKUP"
