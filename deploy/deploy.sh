#!/usr/bin/env bash
# Deploy the latest main on the droplet: pull, rebuild, restart.
# Migrations run automatically when the api container starts.
set -euo pipefail

cd "$(dirname "$0")/.."

[ -f .env.prod ] || { echo "Missing .env.prod (copy .env.prod.example)"; exit 1; }

COMPOSE="docker compose --env-file .env.prod -f docker-compose.prod.yml"

git pull --ff-only
$COMPOSE up -d --build --remove-orphans
$COMPOSE ps
docker image prune -f
