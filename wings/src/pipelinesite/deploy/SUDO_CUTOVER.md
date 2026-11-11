# WINGS cutover: gunicorn + nginx (+ optional HTTPS)

Run these on **burbidge** after the package updates are in place.
Paths assume this repo at `/data/ckilpatrick/WINGS`.

## 0. Stop the old runserver / temporary gunicorn (no sudo)

```bash
pkill -f 'manage.py runserver' || true
pkill -f 'gunicorn pipelinesite.wsgi' || true
sleep 1
ss -ltnp | grep 8000 || echo '8000 free'
```

## 1. Install and start the systemd unit

```bash
sudo cp /data/ckilpatrick/WINGS/wings/src/pipelinesite/deploy/wings-pipelinesite.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now wings-pipelinesite.service
sudo systemctl status wings-pipelinesite.service --no-pager
```

Confirm gunicorn is on localhost only:

```bash
ss -ltnp | grep 8000
curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/accounts/login/
```

## 2. Disable broken JupyterHub nginx SSL sites

These currently make `nginx -t` fail (missing EXAMPLE.COM certs):

```bash
sudo mv /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/default.disabled-jupyter || true
sudo mv /etc/nginx/sites-enabled/jupyterhub.conf /etc/nginx/sites-enabled/jupyterhub.conf.disabled || true
```

## 3. Install the WINGS HTTP site

Move broken Jupyter SSL configs **out of** `sites-enabled` (a `.disabled` rename is not enough; nginx includes `sites-enabled/*`):

```bash
sudo mkdir -p /etc/nginx/disabled-sites
sudo mv /etc/nginx/sites-enabled/default.disabled-jupyter /etc/nginx/disabled-sites/ 2>/dev/null || true
sudo mv /etc/nginx/sites-enabled/jupyterhub.conf.disabled /etc/nginx/disabled-sites/ 2>/dev/null || true
sudo mv /etc/nginx/sites-enabled/default /etc/nginx/disabled-sites/ 2>/dev/null || true
sudo mv /etc/nginx/sites-enabled/jupyterhub.conf /etc/nginx/disabled-sites/ 2>/dev/null || true
```

Free port 80 if Apache is holding it:

```bash
sudo systemctl stop apache2
sudo systemctl disable apache2
```

```bash
sudo cp /data/ckilpatrick/WINGS/wings/src/pipelinesite/deploy/nginx-wings.conf /etc/nginx/sites-available/wings
sudo ln -sf /etc/nginx/sites-available/wings /etc/nginx/sites-enabled/wings
sudo nginx -t
sudo systemctl start nginx
sudo systemctl reload nginx
curl -sS -o /dev/null -w '%{http_code}\n' -H 'Host: burbidge.northwestern.edu' http://127.0.0.1/accounts/login/
```


## 4. Firewall (only if UFW is active)

```bash
sudo ufw status
```

If UFW is active and 80/443 are not allowed:

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

## 5. HTTPS (optional; blocked until campus IT opens 80/443 + DNS)

Certbot previously failed with an ACME timeout (host not reachable from the
public internet). Leave HTTP until IT allows inbound **TCP 80 + 443** and
`burbidge.northwestern.edu` resolves here. Then:

```bash
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d burbidge.northwestern.edu --agree-tos -m ckilpatrick@northwestern.edu --redirect
sudo nginx -t && sudo systemctl reload nginx
```

If certbot succeeds, set HTTPS cookies for the app:

```bash
sudo systemctl edit wings-pipelinesite.service
```

Add:

```ini
[Service]
Environment=PIPELINESITE_HTTPS=1
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl restart wings-pipelinesite.service
```

Manual HTTPS nginx reference (only if certbot did not edit the site):  
`deploy/nginx-wings-https.conf.example`

## Rollback

```bash
sudo systemctl disable --now wings-pipelinesite.service
sudo rm -f /etc/nginx/sites-enabled/wings
# optionally restore jupyter sites:
# sudo mv /etc/nginx/sites-enabled/default.disabled-jupyter /etc/nginx/sites-enabled/default
# sudo mv /etc/nginx/sites-enabled/jupyterhub.conf.disabled /etc/nginx/sites-enabled/jupyterhub.conf
sudo nginx -t && sudo systemctl reload nginx
cd /data/ckilpatrick/WINGS/wings/src/pipelinesite
PIPELINESITE_DEMO=1 nohup ./.venv/bin/python manage.py runserver 0.0.0.0:8000 >/tmp/wings-runserver.log 2>&1 &
```
