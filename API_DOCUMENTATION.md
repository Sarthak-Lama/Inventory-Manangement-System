# Inventory Management System — API Documentation

## Project Overview

A Django REST Framework backend for managing stock items, suppliers, purchase/sale orders, and generating inventory reports. Secured with JWT authentication.

---

## Tech Stack

| Component | Library |
|-----------|---------|
| Framework | Django 4.x + Django REST Framework |
| Auth | `djangorestframework-simplejwt` |
| Filtering | `django-filter` |
| Database | SQLite (dev) / PostgreSQL (prod) |

---

## Setup & Run

```bash
pip install django djangorestframework djangorestframework-simplejwt django-filter

cd inventory_project
python manage.py migrate
python manage.py seed_data        # Creates admin user + sample data
python manage.py runserver
```

**Default admin credentials:** `admin` / `admin1234`

---

## Authentication

All endpoints (except login) require a JWT Bearer token.

### Login
`POST /api/auth/login/`

**Request:**
```json
{ "username": "admin", "password": "admin1234" }
```

**Response `200`:**
```json
{
  "access": "eyJhbGciOiJIUzI1...",
  "refresh": "eyJhbGciOiJIUzI1..."
}
```

Use the access token in subsequent requests:
```
Authorization: Bearer <access_token>
```

### Refresh Token
`POST /api/auth/refresh/`

```json
{ "refresh": "<refresh_token>" }
```

### Register New User (Admin only)
`POST /api/auth/register/`

```json
{
  "username": "warehouse_staff",
  "email": "staff@example.com",
  "password": "securepass123",
  "first_name": "Jane",
  "last_name": "Doe"
}
```

### Get / Update Profile
`GET/PUT /api/auth/profile/`

---

## Suppliers

| Method | URL | Description |
|--------|-----|-------------|
| `GET` | `/api/suppliers/` | List all suppliers |
| `POST` | `/api/suppliers/` | Create supplier |
| `GET` | `/api/suppliers/{id}/` | Get supplier |
| `PUT/PATCH` | `/api/suppliers/{id}/` | Update supplier |
| `DELETE` | `/api/suppliers/{id}/` | Delete supplier |
| `GET` | `/api/suppliers/{id}/items/` | Items from this supplier |
| `GET` | `/api/suppliers/{id}/orders/` | Orders from this supplier |

**Query params:** `search=name`, `ordering=name`

**Sample POST body:**
```json
{
  "name": "TechCorp Ltd",
  "contact_name": "John Smith",
  "email": "orders@techcorp.com",
  "phone": "+1-555-0101",
  "address": "123 Industrial Ave, NY",
  "is_active": true
}
```

**Response `201`:**
```json
{
  "id": 1,
  "name": "TechCorp Ltd",
  "contact_name": "John Smith",
  "email": "orders@techcorp.com",
  "phone": "+1-555-0101",
  "is_active": true,
  "item_count": 0,
  "created_at": "2024-01-15T10:00:00Z"
}
```

---

## Categories

| Method | URL | Description |
|--------|-----|-------------|
| `GET` | `/api/categories/` | List categories |
| `POST` | `/api/categories/` | Create category |
| `GET/PUT/DELETE` | `/api/categories/{id}/` | Manage category |

**Sample body:**
```json
{ "name": "Electronics", "description": "Electronic devices and accessories" }
```

---

## Stock Items

| Method | URL | Description |
|--------|-----|-------------|
| `GET` | `/api/stock-items/` | List all items |
| `POST` | `/api/stock-items/` | Create item |
| `GET` | `/api/stock-items/{id}/` | Item detail |
| `PUT/PATCH` | `/api/stock-items/{id}/` | Update item |
| `DELETE` | `/api/stock-items/{id}/` | Delete item |
| `POST` | `/api/stock-items/{id}/adjust_stock/` | Adjust quantity |
| `GET` | `/api/stock-items/{id}/transactions/` | Transaction history |

**Query params:**
- `search=laptop` — search name/SKU/description
- `category=1` — filter by category ID
- `supplier=2` — filter by supplier ID
- `is_active=true`
- `ordering=quantity_in_stock`

**Sample POST body:**
```json
{
  "sku": "ELEC-003",
  "name": "USB-C Hub",
  "description": "7-port USB-C hub with HDMI",
  "category": 1,
  "supplier": 1,
  "unit": "pcs",
  "unit_price": "49.99",
  "quantity_in_stock": 50,
  "reorder_level": 10,
  "reorder_quantity": 30,
  "is_active": true
}
```

**Response `201`:**
```json
{
  "id": 6,
  "sku": "ELEC-003",
  "name": "USB-C Hub",
  "category_name": "Electronics",
  "supplier_name": "TechCorp Ltd",
  "unit": "pcs",
  "unit_price": "49.99",
  "quantity_in_stock": 50,
  "reorder_level": 10,
  "reorder_quantity": 30,
  "needs_reorder": false,
  "stock_value": "2499.50",
  "is_active": true
}
```

### Adjust Stock
`POST /api/stock-items/{id}/adjust_stock/`

Use positive values to add stock, negative to remove.

```json
{ "quantity": -5, "notes": "Damaged goods removed" }
```

**Response `200`:**
```json
{
  "sku": "ELEC-003",
  "name": "USB-C Hub",
  "previous_quantity": 50,
  "adjusted_by": -5,
  "new_quantity": 45,
  "needs_reorder": false
}
```

---

## Orders

| Method | URL | Description |
|--------|-----|-------------|
| `GET` | `/api/orders/` | List orders |
| `POST` | `/api/orders/` | Create order |
| `GET` | `/api/orders/{id}/` | Order detail |
| `PUT/PATCH` | `/api/orders/{id}/` | Update order |
| `DELETE` | `/api/orders/{id}/` | Delete order |
| `POST` | `/api/orders/{id}/update_status/` | Change status |

**Order types:** `purchase`, `sale`

**Status flow:** `pending → approved → shipped → received` (or `cancelled`)

> When a **purchase order** is set to `received`, stock quantities are automatically incremented and a transaction record is created.

**Sample POST body (Purchase Order):**
```json
{
  "order_type": "purchase",
  "supplier": 1,
  "expected_delivery": "2024-02-01",
  "notes": "Urgent restock",
  "items": [
    { "stock_item": 2, "quantity": 50, "unit_price": "29.99" },
    { "stock_item": 5, "quantity": 20, "unit_price": "22.50" }
  ]
}
```

**Response `201`:**
```json
{
  "id": 1,
  "order_number": "PO-A3F7B2C1",
  "order_type": "purchase",
  "supplier": 1,
  "supplier_name": "TechCorp Ltd",
  "status": "pending",
  "total_amount": "1949.50",
  "items": [
    {
      "id": 1,
      "stock_item": 2,
      "stock_item_name": "Wireless Mouse",
      "stock_item_sku": "ELEC-002",
      "quantity": 50,
      "unit_price": "29.99",
      "subtotal": "1499.50"
    }
  ],
  "created_at": "2024-01-15T12:00:00Z"
}
```

### Update Order Status
`POST /api/orders/{id}/update_status/`

```json
{ "status": "received" }
```

---

## Stock Transactions (Read-only)

| Method | URL | Description |
|--------|-----|-------------|
| `GET` | `/api/transactions/` | All transactions |
| `GET` | `/api/transactions/{id}/` | Single transaction |

**Query params:** `transaction_type=in`, `stock_item=3`, `ordering=-created_at`

**Sample response:**
```json
{
  "id": 10,
  "stock_item": 2,
  "stock_item_name": "Wireless Mouse",
  "transaction_type": "in",
  "quantity": 50,
  "previous_quantity": 3,
  "new_quantity": 53,
  "order": 1,
  "notes": "Received via order PO-A3F7B2C1",
  "created_by_username": "admin",
  "created_at": "2024-01-15T14:00:00Z"
}
```

---

## Reports

All report endpoints: `GET /api/reports/{report_type}/`

### Stock Summary
`GET /api/reports/stock-summary/`

```json
{
  "total_active_items": 5,
  "total_stock_value": 23450.75,
  "low_stock_items": 3,
  "out_of_stock_items": 1,
  "by_category": [
    { "category__name": "Electronics", "count": 2, "total_qty": 28 },
    { "category__name": "Office Supplies", "count": 2, "total_qty": 208 }
  ]
}
```

### Reorder Alerts
`GET /api/reports/reorder-alerts/`

Returns all items where `quantity_in_stock <= reorder_level`.

```json
{
  "count": 3,
  "alerts": [
    {
      "id": 2,
      "sku": "ELEC-002",
      "name": "Wireless Mouse",
      "quantity_in_stock": 3,
      "reorder_level": 10,
      "reorder_quantity": 50,
      "supplier": "TechCorp Ltd",
      "shortage": 7
    }
  ]
}
```

### Low Stock (Critical)
`GET /api/reports/low-stock/`

Items with `quantity_in_stock <= 5`.

### Order Summary
`GET /api/reports/order-summary/`

```json
{
  "by_status_and_type": [
    { "status": "pending", "order_type": "purchase", "count": 2 }
  ],
  "orders_last_30_days": 4,
  "total_orders": 10
}
```

### Stock Valuation
`GET /api/reports/stock-valuation/`

```json
{
  "total_valuation": 23450.75,
  "by_category": {
    "Electronics": { "count": 2, "value": 22975.25 },
    "Office Supplies": { "count": 2, "value": 454.00 }
  }
}
```

### Transaction History
`GET /api/reports/transaction-history/?days=30`

```json
{
  "period_days": 30,
  "summary": [
    { "transaction_type": "in", "count": 8, "total_qty": 250 },
    { "transaction_type": "out", "count": 3, "total_qty": -15 }
  ]
}
```

---

## Data Models

```
Supplier ──< StockItem >── Category
    |
    └──< Order >──< OrderItem >── StockItem
                        |
                   StockTransaction
```

### Unit Choices
`pcs`, `kg`, `g`, `l`, `ml`, `box`, `pack`

### Order Status Flow
`pending → approved → shipped → received / cancelled`

---

## Running Tests

```bash
python manage.py test inventory
```

8 tests covering: auth, JWT, stock CRUD, stock adjustment, order creation, auto-stock-update on receive, and report endpoints.

---

## Production Checklist

- Replace `SECRET_KEY` with a secure value
- Set `DEBUG = False`
- Switch `DATABASES` to PostgreSQL
- Configure `ALLOWED_HOSTS`
- Set `ACCESS_TOKEN_LIFETIME` as appropriate
- Add `CORS_ALLOWED_ORIGINS` if frontend is on a different origin
