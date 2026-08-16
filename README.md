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



  # API Reference

Base URL (local dev): `http://127.0.0.1:8000/api`

All endpoints except `/auth/login/` and `/auth/refresh/` require an `Authorization: Bearer <access_token>` header.
Interactive docs are also available at `/swagger/` and `/redoc/`.

---

## Authentication

### `POST /auth/login/`
No auth required.

**Request**
```json
{ "username": "alice", "password": "hunter2" }
```

**Response — 200**
```json
{
  "access": "eyJhbGciOi...",
  "refresh": "eyJhbGciOi...",
  "user": { "id": 3, "username": "alice", "email": "alice@example.com", "is_staff": true }
}
```

**Response — 401** (wrong credentials)
```json
{ "detail": "No active account found with the given credentials" }
```

Access tokens expire after **30 minutes**. Login is throttled to **10 requests/minute** per client.

---

### `POST /auth/refresh/`
No auth required.

**Request**
```json
{ "refresh": "eyJhbGciOi..." }
```

**Response — 200**
```json
{ "access": "eyJhbGciOi...", "refresh": "eyJhbGciOi..." }
```
A new refresh token is issued on every call (rotation) and the old one is blacklisted immediately.

**Response — 401** (expired, already used, or blacklisted)
```json
{ "detail": "Token is invalid or expired", "code": "token_not_valid" }
```

---

### `POST /auth/logout/`
Requires auth.

**Request**
```json
{ "refresh": "eyJhbGciOi..." }
```

**Response — 205**
```json
{ "detail": "Successfully logged out." }
```

**Response — 400** (missing or already-invalid token)
```json
{ "error": "A \"refresh\" token is required to log out." }
```

---

### `POST /auth/register/`
**Staff/admin only.** Creates a new user account.

**Request**
```json
{ "username": "bob", "email": "bob@example.com", "password": "SecurePass123!" }
```

**Response — 201**
```json
{ "id": 4, "username": "bob", "email": "bob@example.com", "first_name": "", "last_name": "", "is_staff": false }
```

**Response — 403** (non-staff caller)
```json
{ "detail": "You do not have permission to perform this action." }
```

---

### `GET/PATCH /auth/profile/`
Requires auth. Returns/updates the logged-in user's own profile. `is_staff` cannot be changed through this endpoint.

---

## Suppliers — `/suppliers/`

Standard REST resource (`list`, `retrieve`, `create`, `update`, `partial_update`, `destroy`).
**Read: any authenticated user. Write: staff only.**

| Field | Notes |
|---|---|
| `name` | required, unique (case-insensitive) |
| `contact_name`, `phone`, `address` | optional |
| `email` | optional, unique if provided |

**Extra actions:**
- `GET /suppliers/{id}/items/` — active stock items from this supplier
- `GET /suppliers/{id}/orders/` — orders placed with this supplier

**Error — duplicate name (400)**
```json
{ "name": ["A supplier with this name already exists."] }
```

---

## Categories — `/categories/`

Same shape as Suppliers: `name` (required, unique), `description` (optional). Read: all authenticated users. Write: staff only.

---

## Stock Items — `/stock-items/`

Read: all authenticated users. Write: staff only.
Filters: `?category=<id>&supplier=<id>&is_active=true&unit=pcs`
Search: `?search=<text>` (matches name, SKU, description)
Ordering: `?ordering=name` / `?ordering=-quantity_in_stock` etc.

**Create/Update request**
```json
{
  "sku": "ELEC-001",
  "name": "USB-C Cable",
  "description": "1m braided",
  "category": 2,
  "supplier": 1,
  "unit_price": "8.99",
  "quantity_in_stock": 100,
  "reorder_level": 20,
  "reorder_quantity": 50
}
```

**Validation error — 400** (several failures shown together)
```json
{
  "sku": ["A stock item with SKU 'ELEC-001' already exists."],
  "unit_price": ["Unit price must be greater than zero."],
  "quantity_in_stock": ["Quantity in stock cannot be negative."]
}
```

**Delete a referenced item — 409**
```json
{
  "error": "Cannot delete 'USB-C Cable' (ELEC-001): it appears on one or more orders and deleting it would break that order history.",
  "suggestion": "Set is_active=False instead (PATCH this item with {\"is_active\": false}) to hide it from active use without losing history."
}
```

### `POST /stock-items/{id}/adjust_stock/`
Manual stock correction. `quantity` is signed: positive adds, negative removes.

**Request**
```json
{ "quantity": -3, "notes": "damaged in warehouse" }
```

**Response — 200**
```json
{ "sku": "ELEC-001", "name": "USB-C Cable", "previous_quantity": 100, "adjusted_by": -3, "new_quantity": 97, "needs_reorder": false }
```

**Response — 400** (would go negative)
```json
{ "error": "Insufficient stock for this adjustment.", "available": 5, "requested_change": -10 }
```

### `POST /stock-items/{id}/deactivate/` / `POST /stock-items/{id}/reactivate/`
Toggles `is_active`. Idempotent — calling twice returns `"detail": "Already inactive."` rather than erroring.

### `GET /stock-items/{id}/transactions/`
Full stock movement history for this item.

---

## Orders — `/orders/`

Read: all authenticated users. Write: staff only.
Filters: `?status=pending&order_type=sale&supplier=<id>`

**Create request**
```json
{
  "order_type": "sale",
  "supplier": null,
  "expected_delivery": "2026-08-20",
  "notes": "Rush order",
  "items": [
    { "stock_item": 5, "quantity": 10, "unit_price": "8.99" },
    { "stock_item": 7, "quantity": 2, "unit_price": "24.00" }
  ]
}
```

Notes:
- `status` is **read-only** here — it always starts at `pending` and can only be changed via `update_status` below.
- Purchase orders (`order_type: "purchase"`) require a `supplier`.
- Once an order leaves `pending`, its `items`, `order_type`, and `supplier` can no longer be edited (only `notes`/`expected_delivery` remain editable).

**Validation error — 400**
```json
{ "supplier": ["A supplier is required for purchase orders."] }
```
```json
{ "items": ["An order must contain at least one item."] }
```

### `POST /orders/{id}/update_status/`
The only way to change an order's status. Enforces this transition graph:

| Order type | `pending` → | `approved` → | `shipped` → |
|---|---|---|---|
| Purchase | `approved`, `cancelled` | `shipped`, `cancelled` | `received`, `cancelled` |
| Sale | `approved`, `cancelled` | `shipped`, `cancelled` | `received`, `cancelled` |

Stock moves automatically and safely:
- Purchase → `received`: stock added for every line item.
- Sale → `shipped`: stock deducted — **rejected if any item lacks sufficient stock** (all-or-nothing, no partial shipment).
- Sale, `shipped` → `cancelled`: the deducted stock is **reversed** (added back), since the shipment never completed.
- `received` and `cancelled` are terminal — no further transitions.

**Request**
```json
{ "status": "shipped" }
```

**Response — 200**
```json
{ "order_number": "SO-4F2A9B1C", "status": "shipped" }
```

**Response — 400** (invalid transition)
```json
{
  "error": "Cannot move a sale order from 'pending' to 'received'.",
  "current_status": "pending",
  "allowed_next_statuses": ["approved", "cancelled"],
  "detail": "From 'pending', this order can only move to: ['approved', 'cancelled']."
}
```

**Response — 400** (insufficient stock to ship)
```json
{
  "error": "Cannot ship order: insufficient stock for one or more items.",
  "shortages": [
    { "sku": "ELEC-001", "name": "USB-C Cable", "available": 4, "requested": 10 }
  ]
}
```

---

## Stock Transactions — `/transactions/`

Read-only. Every stock movement (manual adjustment, order received, order shipped, cancellation reversal) is logged here automatically — you never write to this endpoint directly.

Filters: `?transaction_type=in&stock_item=<id>`
Search: `?search=<text>` (item name/SKU)

---

## Reports — `/reports/{report_type}/`

`report_type` is one of: `stock-summary`, `reorder-alerts`, `low-stock`, `order-summary`, `stock-valuation`, `transaction-history`.

**Common query params** (only apply where relevant to the report type):

| Param | Reports it applies to |
|---|---|
| `category=<id>` | stock-summary, reorder-alerts, low-stock, stock-valuation, transaction-history |
| `supplier=<id>` | all except transaction-history-without-item-link — see note below |
| `start_date=YYYY-MM-DD`, `end_date=YYYY-MM-DD` | order-summary, transaction-history |
| `threshold=<n>` | low-stock (default 5) |
| `days=<n>` | transaction-history (default 7; ignored if `start_date`/`end_date` given) |
| `export=csv` | any report — returns a CSV file download instead of JSON |

**Example**
```
GET /reports/reorder-alerts/?category=2&supplier=1
GET /reports/stock-summary/?export=csv
```

**Response — stock-summary (200)**
```json
{
  "total_active_items": 42,
  "total_stock_value": 15230.50,
  "low_stock_items": 3,
  "out_of_stock_items": 1,
  "by_category": [{ "category__name": "Electronics", "count": 20, "total_qty": 850 }]
}
```

**Response — export=csv (200)**
Headers: `Content-Type: text/csv`, `Content-Disposition: attachment; filename="stock-summary.csv"`. Body is a standard CSV, one row per item.

**Response — unknown report type (404)**
```json
{ "error": "Unknown report type" }
```

---

## Common Error Shapes

| Status | When | Shape |
|---|---|---|
| 400 | Validation failure | `{"field_name": ["message"]}` or `{"error": "message"}` |
| 401 | Missing/expired/invalid token | `{"detail": "...", "code": "..."}` |
| 403 | Authenticated but not staff, on a write action | `{"detail": "You do not have permission to perform this action."}` |
| 404 | Object or report type doesn't exist | `{"detail": "Not found."}` or `{"error": "Unknown report type"}` |
| 409 | Deleting a stock item still referenced by an order | `{"error": "...", "suggestion": "..."}` |
| 429 | Login throttle exceeded (10/min) | `{"detail": "Request was throttled. Expected available in N seconds."}` |


