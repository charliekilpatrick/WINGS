# Handoff: finish optional WINGS updates

Core refactor is already applied (migrate, ingest, artifact rebuild). Remaining
optional pieces: **restart** (middleware/API), **weekly cron**, **HTTPS when IT opens 443**, **smoke + UI check**.

## A. Restart gunicorn (required for this round)

Loads login-exempt `/api/targets/` and `smoke_wings`:

```bash
sudo systemctl restart wings-pipelinesite.service
sudo systemctl status wings-pipelinesite.service --no-pager
```

## B. Smoke check (no sudo)

```bash
cd /data/ckilpatrick/WINGS/wings/src/pipelinesite
export PIPELINESITE_DEMO=1 PIPELINESITE_SERVE=1
export DJANGO_SETTINGS_MODULE=pipelinesite.settings_serve
.venv/bin/python manage.py smoke_wings

curl -sS -o /dev/null -w 'login:%{http_code}\n' http://127.0.0.1:8000/accounts/login/
curl -sS 'http://127.0.0.1:8000/api/targets/?program=18338&tag=empty_mast' | head -c 400; echo
```

Logged-in browser (after login):

- `/` — empty-MAST counts on program cards
- `/programs/18338` — Status / Field filters; `no data yet (0/0)` rows
- Open an empty-MAST target — grey empty-field banner
- `/api/targets/?program=18338&tag=empty_mast&role=prime`

## C. Weekly artifact cron (add one crontab line)

Script is already installed at `/home/ckilpatrick/cron/ngp_artifacts.sh`.

```bash
chmod +x /home/ckilpatrick/cron/ngp_artifacts.sh
crontab -e
```

Add next to the existing NGP lines:

```cron
# NGP / WINGS page inventory + preview warm (missing caches only)
30 3 * * 0 nice -n 19 /home/ckilpatrick/cron/ngp_artifacts.sh
```

Existing MAST cron is already correct (no change):

```cron
20 4 * * * nice -n 19 /home/ckilpatrick/cron/ngp_mast.sh
```

Dry-run once (optional):

```bash
nice -n 19 /home/ckilpatrick/cron/ngp_artifacts.sh
# then: ls /home/ckilpatrick/cron/logs/ngp_artifacts/
```

## D. HTTPS (blocked until campus firewall / DNS allow ACME)

HTTP on :80 is fine until then. When IT opens **inbound 80 + 443** to
`burbidge.northwestern.edu` and DNS points here:

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d burbidge.northwestern.edu \
  --agree-tos -m ckilpatrick@northwestern.edu --redirect
sudo nginx -t && sudo systemctl reload nginx

sudo systemctl edit wings-pipelinesite.service
# add:
# [Service]
# Environment=PIPELINESITE_HTTPS=1
sudo systemctl daemon-reload
sudo systemctl restart wings-pipelinesite.service
```

Reference nginx HTTPS block (manual restore only):  
`deploy/nginx-wings-https.conf.example`

Ask IT for: public A record + allow ACME HTTP-01 (TCP 80) and HTTPS (TCP 443).

## Already done (do not redo unless schema changes)

- `migrate manager` / `ingest_campaign_index`
- `rebuild_page_artifacts` (231 rebuilt)
- gunicorn + nginx HTTP cutover
- `ngp_mast.sh` / `ngp_targets.sh` (ORM flags update via `check_mast_updates`)
