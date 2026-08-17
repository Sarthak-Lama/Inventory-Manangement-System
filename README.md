# Deployment Guide

This project already includes what it needs for a production-style deployment: `whitenoise` for
static files, `django-cors-headers` for CORS, and settings driven by environment variables. This
guide covers taking it from `runserver` to a real deployment.

---

## 1. Environment Variables

Nothing sensitive is hardcoded — all of it comes from `.env` (local) or your host's environment
variable settings (production). Required:

```env
SECRET_KEY=<random, 50+ characters — never reuse the dev one>
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

DB_ENGINE=django.db.backends.postgresql
DB_NAME=inventory_prod
DB_USER=inventory_app
DB_PASSWORD=<strong, unique password>
DB_HOST=<your db host>
DB_PORT=5432

CORS_ALLOWED_ORIGINS=https://yourfrontend.com
```

Generate a real `SECRET_KEY`:
```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

**Never commit `.env` to version control.** Add it to `.gitignore` if it isn't already.

---

## 2. Pre-Deployment Checklist

- [ ] `DEBUG=False` — leaving this on in production leaks stack traces and settings to anyone who hits an error.
- [ ] `ALLOWED_HOSTS` set to your actual domain(s), not `*`.
- [ ] `CORS_ALLOWED_ORIGINS` set to your actual frontend origin(s), not left wide open.
- [ ] `SECRET_KEY` is unique to this environment and not the same as dev/staging.
- [ ] Database credentials are unique to this environment.
- [ ] HTTPS is terminated somewhere in front of the app (load balancer, reverse proxy, or platform-managed) — JWTs in the `Authorization` header are only as safe as the transport they travel over.

Recommended additions to `settings.py` once you're behind HTTPS:
```python
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
```

---

## 3. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

If you don't have a `requirements.txt` yet, generate one from your working dev environment:
```bash
pip freeze > requirements.txt
```
At minimum it needs: `django`, `djangorestframework`, `djangorestframework-simplejwt`,
`django-filter`, `drf-yasg`, `django-cors-headers`, `python-decouple`, `psycopg2-binary`,
`whitenoise`, and a WSGI server (`gunicorn`).

```bash
pip install gunicorn
```

---

## 4. Database

1. Provision a PostgreSQL database (managed service — RDS, Cloud SQL, etc. — or self-hosted).
2. Point `DB_*` env vars at it.
3. Run migrations:
```bash
python manage.py migrate
```
This includes the `token_blacklist` tables required for logout to work — don't skip it even if
the app "seems" to run without it; logout will silently 500 without these tables.

4. Create your first admin/staff account:
```bash
python manage.py createsuperuser
```

---

## 5. Static Files

`whitenoise` is already wired into `MIDDLEWARE`, so static files can be served directly by the
app process without a separate nginx/S3 setup (fine for small-to-medium deployments; move to a
CDN/object storage later if traffic grows).

```bash
python manage.py collectstatic --noinput
```
This populates `STATIC_ROOT` (`staticfiles/`). Run this on every deploy, after installing
dependencies and before starting the server.

---

## 6. Running the Server

**Do not use `python manage.py runserver` in production** — it's single-threaded, unoptimized,
and Django itself warns against it. Use a real WSGI server:

```bash
gunicorn inventory_project.wsgi:application --bind 0.0.0.0:8000 --workers 3
```

Tune `--workers` roughly to `(2 × CPU cores) + 1`. Put this behind a process manager (systemd,
supervisor, or your platform's equivalent) so it restarts automatically on crash or reboot.

**Example systemd unit** (`/etc/systemd/system/inventory.service`):
```ini
[Unit]
Description=Inventory Management API
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/inventory_project
EnvironmentFile=/opt/inventory_project/.env
ExecStart=/opt/inventory_project/venv/bin/gunicorn inventory_project.wsgi:application --bind 127.0.0.1:8000 --workers 3
Restart=always

[Install]
WantedBy=multi-user.target
```

Then front it with nginx (or similar) for TLS termination and to serve as a reverse proxy —
gunicorn should not be exposed directly to the internet.

---

## 7. Deploy Checklist (every deploy)

```bash
git pull
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py test inventory   # don't skip this — see below
sudo systemctl restart inventory  # or your platform's equivalent
```

**Run the test suite before every deploy.** `python manage.py test inventory` covers validation,
stock-safety locking, the order state machine, auth, and reports — a regression in any of these
(e.g. someone loosening a permission check, or breaking the stock-negative guard) will fail loudly
here instead of silently in production.

---

## 8. Frontend

The frontend (`index.html` / `app.js` / `style.css`) is static and framework-free — it can be
served from the same whitenoise setup, a separate static host (Netlify, Vercel, S3+CloudFront),
or any web server. The only thing that needs to change per environment is the `API` constant at
the top of `app.js`:

```js
const API = 'https://api.yourdomain.com/api';
```

Make sure this points at your deployed backend, and that the backend's `CORS_ALLOWED_ORIGINS`
includes wherever the frontend is actually hosted.

---

## 9. Monitoring & Backups (not yet built — recommended next steps)

- **Database backups**: set up automated daily backups if your DB host doesn't already do this.
- **Error tracking**: consider Sentry or similar — right now, exceptions only show up in server
  logs.
- **Health check endpoint**: none currently exists; add a simple `GET /api/health/` returning
  `200 OK` if you're putting this behind a load balancer that expects one.


