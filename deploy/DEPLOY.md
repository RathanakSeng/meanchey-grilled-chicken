# Production deployment (DigitalOcean + Cloudflare)

One droplet runs three containers from `docker-compose.prod.yml`:

| Service | Role |
|---|---|
| `web` | nginx: TLS (Cloudflare Origin Certificate), serves the UI, proxies `/api/*` and `/health` to `api`. The only service with published ports (80, 443). |
| `api` | FastAPI. On every start it runs `alembic upgrade head`, then `python -m app.bootstrap`, then uvicorn, so **deploys migrate automatically**. |
| `postgres` | Postgres 16, data in the `pgdata` volume, not published. |

Telegram runs in webhook mode inside `api` (`/api/telegram/webhook`); there is no separate bot process.

## One-time setup

### 1. Droplet
- Ubuntu LTS, 2 GB RAM or more (the UI build runs on the droplet). Add swap if you use 1 GB.
- Install Docker Engine and the compose plugin: https://docs.docker.com/engine/install/ubuntu/
- Firewall (`ufw allow OpenSSH && ufw allow 80,443/tcp && ufw enable`). Do not expose 5432 or 8000.
- Enable DigitalOcean weekly backups (optional but recommended).

### 2. Cloudflare
1. DNS: `A` record for your domain (or subdomain) to the droplet IP, **Proxied** (orange cloud).
2. SSL/TLS -> Overview: set mode to **Full (strict)**.
3. SSL/TLS -> Origin Server -> Create Certificate (15 years). Save on the droplet:
   ```bash
   sudo mkdir -p /etc/ssl/cloudflare
   sudo nano /etc/ssl/cloudflare/origin.pem   # certificate
   sudo nano /etc/ssl/cloudflare/origin.key   # private key
   sudo chmod 600 /etc/ssl/cloudflare/origin.key
   ```
4. Do not put a WAF/bot challenge on `/api/telegram/webhook`: Telegram must reach it.

### 3. App
```bash
git clone <repo-url> /opt/meanchey && cd /opt/meanchey
cp .env.prod.example .env.prod
nano .env.prod          # fill every secret, domain, Telegram values
chmod +x deploy/*.sh
./deploy/deploy.sh
```
Set `MINI_APP_URL` and `TELEGRAM_WEBHOOK_URL` to `https://<domain>` and `https://<domain>/api/telegram/webhook`. Change `SUPERADMIN_INITIAL_PASSWORD` before the first start (it is only used when the superadmin is first seeded).

## Deploying updates
```bash
cd /opt/meanchey && ./deploy/deploy.sh
```
`git pull` -> rebuild images -> recreate changed containers. The new `api` container migrates the database before it becomes healthy; `web` waits for that. Keep migrations backward compatible with the running version, since the old container is stopped only after the new image is built (expect a few seconds of downtime while it restarts).

`.env.prod` is read only when a container is created. After editing it: `docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --force-recreate api`.

## Operations
```bash
C="docker compose --env-file .env.prod -f docker-compose.prod.yml"
$C ps
$C logs -f api
$C exec api alembic current
```
- **Backups:** `deploy/backup.sh` (cron suggestion inside). Restore: `gunzip -c backups/<file>.sql.gz | $C exec -T postgres psql -U meanchey meanchey` into an empty database.
- **Telegram check:** `curl https://api.telegram.org/bot<TOKEN>/getWebhookInfo` should show your URL and no `last_error_message`.
- **Health:** `curl https://<domain>/health` returns `{"status":"ok"}`.

## Notes
- Real visitor IPs are restored from `CF-Connecting-IP` using Cloudflare's published ranges in `meanchey-grilled-chicken-ui/deploy/cloudflare-real-ip.conf`.
- To lock the origin down further, allow only Cloudflare IP ranges on 80/443 in `ufw`.
