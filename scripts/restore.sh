#!/usr/bin/env sh
# Restore a backup made by scripts/backup.sh. DESTRUCTIVE: it replaces the
# deployment's database contents and artefacts with the backup's.
#
#   scripts/restore.sh <backup-directory> --yes
#
# Refuses without --yes, and refuses if a checksum in MANIFEST does not
# match. Stop the backend first (`docker compose -f docker-compose.prod.yml
# stop backend frontend`) so no run writes while the restore is in progress.
# Rehearse on a scratch database with scripts/rehearse_restore.sh before
# relying on this.
set -eu

DIR="${1:?usage: scripts/restore.sh <backup-directory> --yes}"
[ "${2:-}" = "--yes" ] || { echo "refusing: this replaces the database and artefacts; pass --yes" >&2; exit 2; }
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
compose() { docker compose -f "$COMPOSE_FILE" "$@"; }

for name in database.dump artefacts.tar.gz; do
  expected="$(grep "^$name " "$DIR/MANIFEST" | sed 's/.*sha256=\([0-9a-f]*\).*/\1/')"
  actual="$(sha256sum "$DIR/$name" | cut -d' ' -f1)"
  [ "$expected" = "$actual" ] || { echo "checksum mismatch for $name; not restoring" >&2; exit 1; }
done

echo "restoring the database..."
compose exec -T db sh -c 'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < "$DIR/database.dump"

echo "restoring artefacts..."
compose run --rm --no-deps --entrypoint sh -v "$(cd "$DIR" && pwd):/backup:ro" backend \
  -c 'find /storage -mindepth 1 -delete && tar -xzf /backup/artefacts.tar.gz -C /storage'

echo "restored from $DIR; start the stack and check /api/v1/health"
