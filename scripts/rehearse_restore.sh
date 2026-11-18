#!/usr/bin/env sh
# Rehearse a restore without touching the source: dump the database, restore
# the dump into a new scratch database on the same server, and compare every
# table's row count with the source. Exits non-zero on any difference.
#
#   scripts/rehearse_restore.sh                 # development compose file
#   COMPOSE_FILE=docker-compose.prod.yml scripts/rehearse_restore.sh
#
# The scratch database is created fresh and dropped at the end; the source
# database is only read.
set -eu

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
SCRATCH="bhashabench_restore_rehearsal"
compose() { docker compose -f "$COMPOSE_FILE" "$@"; }
psql_in() { compose exec -T db sh -c "psql -v ON_ERROR_STOP=1 -U \"\$POSTGRES_USER\" -d $1 -tAc \"$2\""; }

TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

echo "1/4 dumping the source database (read-only)..."
compose exec -T db sh -c 'pg_dump -Fc -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > "$TMP"
echo "    $(wc -c < "$TMP") bytes"

echo "2/4 restoring into the scratch database $SCRATCH..."
psql_in postgres "DROP DATABASE IF EXISTS $SCRATCH"
psql_in postgres "CREATE DATABASE $SCRATCH"
compose exec -T db sh -c "pg_restore --no-owner -U \"\$POSTGRES_USER\" -d $SCRATCH" < "$TMP"

echo "3/4 comparing row counts..."
SOURCE_DB="$(compose exec -T db sh -c 'printf %s "$POSTGRES_DB"')"
TABLES="$(psql_in "$SOURCE_DB" "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1")"
FAILED=0
for t in $TABLES; do
  a="$(psql_in "$SOURCE_DB" "SELECT count(*) FROM \\\"$t\\\"")"
  b="$(psql_in "$SCRATCH" "SELECT count(*) FROM \\\"$t\\\"")"
  if [ "$a" = "$b" ]; then echo "    ok   $t $a"; else echo "    DIFF $t source=$a restored=$b"; FAILED=1; fi
done

echo "4/4 dropping the scratch database..."
psql_in postgres "DROP DATABASE $SCRATCH"

[ "$FAILED" = 0 ] && echo "restore rehearsal PASSED" || { echo "restore rehearsal FAILED"; exit 1; }
