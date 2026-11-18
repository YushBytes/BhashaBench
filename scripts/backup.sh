#!/usr/bin/env sh
# Back up a BhashaBench deployment: the database and the artefact volume.
#
#   scripts/backup.sh [output-directory]          # default ./backups/<UTC timestamp>
#
# Writes two files and a manifest:
#   database.dump    pg_dump custom format (compressed; restored with pg_restore)
#   artefacts.tar.gz the audio artefacts and recordings (/storage)
#   MANIFEST         what was taken, when, from which compose project, and checksums
#
# Read-only against the running system: nothing is stopped, locked beyond what
# pg_dump's snapshot needs, or modified. Uses the production compose file
# unless COMPOSE_FILE is set. Credentials come from the db container's own
# environment, so none is passed on the command line.
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="${1:-backups/$STAMP}"
mkdir -p "$OUT"

compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

echo "dumping the database..."
compose exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$OUT/database.dump"

echo "archiving artefacts..."
compose run --rm --no-deps --entrypoint sh -v "$(cd "$OUT" && pwd):/backup" backend \
  -c 'tar -czf /backup/artefacts.tar.gz -C /storage .'

{
  echo "taken_at=$STAMP"
  echo "compose_file=$COMPOSE_FILE"
  echo "database.dump sha256=$(sha256sum "$OUT/database.dump" | cut -d' ' -f1) bytes=$(wc -c < "$OUT/database.dump")"
  echo "artefacts.tar.gz sha256=$(sha256sum "$OUT/artefacts.tar.gz" | cut -d' ' -f1) bytes=$(wc -c < "$OUT/artefacts.tar.gz")"
} > "$OUT/MANIFEST"

echo "backup written to $OUT"
cat "$OUT/MANIFEST"
