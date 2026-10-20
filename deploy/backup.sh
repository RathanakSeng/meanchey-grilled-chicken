#!/usr/bin/env bash
# Dump the production database to ./backups (keeps the newest 14). Run from cron, e.g.
#   0 3 * * * /opt/meanchey/deploy/backup.sh >> /var/log/meanchey-backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."
mkdir -p backups

COMPOSE="docker compose --env-file .env.prod -f docker-compose.prod.yml"
FILE="backups/meanchey-$(date +%F-%H%M).sql.gz"

$COMPOSE exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' | gzip > "$FILE"
ls -1t backups/meanchey-*.sql.gz | tail -n +15 | xargs -r rm --
echo "wrote $FILE"
