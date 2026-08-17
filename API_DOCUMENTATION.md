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

