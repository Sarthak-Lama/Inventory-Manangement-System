// ────────────────────────────────────────────────────────
//  CONFIGURATION
// ────────────────────────────────────────────────────────
const API = 'http://127.0.0.1:8000/api';

// ────────────────────────────────────────────────────────
//  AUTH HELPERS
// ────────────────────────────────────────────────────────
const getToken   = () => localStorage.getItem('access_token');
const getRefresh = () => localStorage.getItem('refresh_token');
const getUser    = () => JSON.parse(localStorage.getItem('user') || '{}');
const isStaff    = () => !!getUser().is_staff;

function authHeaders() {
  return {
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${getToken()}`
  };
}

// Grabs the most useful error message out of a DRF error response,
// whatever shape it came back in — {"error": "..."}, {"detail": "..."},
// or field-level {"sku": ["already exists"]}.
function firstApiError(data, fallback = 'Request failed') {
  if (!data) return fallback;
  if (data.error) return data.error;
  if (data.detail) return data.detail;
  for (const key of Object.keys(data)) {
    if (key.startsWith('__')) continue;
    const val = data[key];
    if (Array.isArray(val) && val.length) return `${key}: ${val[0]}`;
    if (typeof val === 'string') return val;
  }
  return fallback;
}

// Uses the refresh token to get a new access token without kicking the
// user back to the login screen. Access tokens now expire in 30 minutes,
// so this matters a lot more than it used to.
async function tryRefreshToken() {
  const refresh = getRefresh();
  if (!refresh) return false;
  try {
    const res = await fetch(`${API}/auth/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh })
    });
    if (!res.ok) return false;
    const data = await res.json();
    localStorage.setItem('access_token', data.access);
    // ROTATE_REFRESH_TOKENS is on server-side, so a fresh refresh token
    // comes back too — the old one is now blacklisted, keep the new one.
    if (data.refresh) localStorage.setItem('refresh_token', data.refresh);
    return true;
  } catch (e) {
    return false;
  }
}

async function apiFetch(path, options = {}) {
  let res = await fetch(`${API}${path}`, { headers: authHeaders(), ...options });

  if (res.status === 401) {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      res = await fetch(`${API}${path}`, { headers: authHeaders(), ...options });
    } else {
      logout();
      return null;
    }
  }

  if (res.status === 204) return { __ok: true, __status: 204 };

  let data = {};
  try { data = await res.json(); } catch (e) { /* empty/non-JSON body */ }
  data.__ok = res.ok;
  data.__status = res.status;
  return data;
}

// ────────────────────────────────────────────────────────
//  TOAST
// ────────────────────────────────────────────────────────
function toast(msg, type = 'success') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast toast-${type}`;
  el.classList.remove('hidden');
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.add('hidden'), 3000);
}

// ────────────────────────────────────────────────────────
//  LOGIN
// ────────────────────────────────────────────────────────
document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const username = document.getElementById('username').value.trim();
  const password = document.getElementById('password').value;
  const errEl    = document.getElementById('login-error');
  errEl.classList.add('hidden');

  const res = await fetch(`${API}/auth/login/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password })
  });

  if (!res.ok) {
    errEl.textContent = 'Invalid username or password.';
    errEl.classList.remove('hidden');
    return;
  }

  const data = await res.json();
  localStorage.setItem('access_token', data.access);
  localStorage.setItem('refresh_token', data.refresh);
  // Login now returns { id, username, email, is_staff } under "user" —
  // store the whole thing so isStaff() and the sidebar have what they need.
  localStorage.setItem('user', JSON.stringify(data.user || { username }));
  showApp();
});

async function logout() {
  const refresh = getRefresh();
  if (refresh) {
    // Blacklist the refresh token server-side so it can't be replayed even
    // if someone captured it earlier. Best-effort — if this fails (token
    // already expired/invalid, network hiccup) we still log out locally.
    try {
      await fetch(`${API}/auth/logout/`, {
        method: 'POST',
        headers: authHeaders(),
        body: JSON.stringify({ refresh })
      });
    } catch (e) { /* ignore — still clearing local state below */ }
  }
  localStorage.clear();
  document.getElementById('app').classList.add('hidden');
  document.getElementById('login-page').classList.remove('hidden');
}

document.getElementById('logout-btn').addEventListener('click', logout);

// ────────────────────────────────────────────────────────
//  APP INIT
// ────────────────────────────────────────────────────────
function showApp() {
  document.getElementById('login-page').classList.add('hidden');
  document.getElementById('app').classList.remove('hidden');
  const user = getUser();
  document.getElementById('user-name').textContent = user.username || 'User';
  document.getElementById('user-avatar').textContent = (user.username || 'U')[0].toUpperCase();

  // Backend now restricts create/edit/delete on suppliers, categories,
  // stock items, and orders to staff users (IsStaffOrReadOnly). Hide the
  // "+ Add" buttons for non-staff so the UI doesn't offer actions that
  // will just come back as a 403.
  ['btn-add-stock', 'btn-add-supplier', 'btn-add-category', 'btn-add-order'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.style.display = isStaff() ? '' : 'none';
  });

  navigateTo('dashboard');
}

// Auto-login if token exists
if (getToken()) showApp();

// ────────────────────────────────────────────────────────
//  NAVIGATION
// ────────────────────────────────────────────────────────
document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => navigateTo(btn.dataset.page));
});

function navigateTo(page) {
  document.querySelectorAll('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.page === page));
  document.querySelectorAll('.page').forEach(p => p.classList.toggle('active', p.id === `page-${page}`));
  loadPage(page);
}

function loadPage(page) {
  if (page === 'dashboard')    loadDashboard();
  if (page === 'stock')        loadStock();
  if (page === 'suppliers')    loadSuppliers();
  if (page === 'categories')   loadCategories();
  if (page === 'orders')       loadOrders();
  if (page === 'transactions') loadTransactions();
  if (page === 'reports' && !reportFiltersLoaded) {
    reportFiltersLoaded = true;
    populateReportFilters();
  }
}

// ────────────────────────────────────────────────────────
//  DASHBOARD
// ────────────────────────────────────────────────────────
async function loadDashboard() {
  const [summary, alerts, orders] = await Promise.all([
    apiFetch('/reports/stock-summary/'),
    apiFetch('/reports/reorder-alerts/'),
    apiFetch('/orders/?ordering=-created_at')
  ]);

  if (summary) {
    document.getElementById('stat-items').textContent  = summary.total_active_items ?? '—';
    document.getElementById('stat-value').textContent  = summary.total_stock_value != null ? `$${Number(summary.total_stock_value).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}` : '—';
    document.getElementById('stat-alerts').textContent = summary.low_stock_items ?? '—';
    document.getElementById('stat-oos').textContent    = summary.out_of_stock_items ?? '—';
  }

  const reorderList = document.getElementById('reorder-list');
  if (alerts && alerts.alerts && alerts.alerts.length) {
    reorderList.innerHTML = alerts.alerts.slice(0, 6).map(a => `
      <div class="alert-item">
        <div>
          <div class="name">${a.name}</div>
          <div class="meta">SKU: ${a.sku} · Supplier: ${a.supplier || 'N/A'}</div>
        </div>
        <span class="badge badge-warn">Qty: ${a.quantity_in_stock} / ${a.reorder_level}</span>
      </div>`).join('');
  } else {
    reorderList.innerHTML = '<div class="empty-state">No reorder alerts</div>';
  }

  const recentList = document.getElementById('recent-orders-list');
  const orderData  = orders && (orders.results || orders);
  if (Array.isArray(orderData) && orderData.length) {
    recentList.innerHTML = orderData.slice(0, 6).map(o => `
      <div class="alert-item">
        <div>
          <div class="name">${o.order_number}</div>
          <div class="meta">${o.supplier_name || 'N/A'} · ${new Date(o.created_at).toLocaleDateString()}</div>
        </div>
        ${statusBadge(o.status)}
      </div>`).join('');
  } else {
    recentList.innerHTML = '<div class="empty-state">No recent orders</div>';
  }
}

// ────────────────────────────────────────────────────────
//  STOCK ITEMS
// ────────────────────────────────────────────────────────
let stockPage = 1;
let stockSearch = '';

async function loadStock(page = 1) {
  stockPage = page;
  const q = stockSearch ? `&search=${encodeURIComponent(stockSearch)}` : '';
  const data = await apiFetch(`/stock-items/?page=${page}${q}`);
  if (!data) return;

  const items = data.results || data;
  const tbody = document.getElementById('stock-body');

  if (!items.length) {
    tbody.innerHTML = '<tr><td colspan="7"><div class="empty-state">No stock items found</div></td></tr>';
    return;
  }

  const staff = isStaff();

  tbody.innerHTML = items.map(i => `
    <tr>
      <td><span class="sku-badge">${i.sku}</span></td>
      <td>${i.name}</td>
      <td>${i.category_name || '—'}</td>
      <td>
        ${i.quantity_in_stock}
        ${i.needs_reorder ? '<span class="badge badge-warn" style="margin-left:6px">Low</span>' : ''}
      </td>
      <td>$${Number(i.unit_price).toFixed(2)}</td>
      <td>${i.is_active ? '<span class="badge badge-success">Active</span>' : '<span class="badge badge-gray">Inactive</span>'}</td>
      <td class="td-actions">
        ${staff ? `
          <button class="btn-icon btn-sm" onclick="adjustStockModal(${i.id}, '${i.name.replace(/'/g,"\\'")}', ${i.quantity_in_stock})">Adjust</button>
          <button class="btn-icon btn-sm" onclick="editStockModal(${i.id})">Edit</button>
          <button class="btn-icon btn-sm" onclick="toggleStockActive(${i.id}, ${i.is_active})">${i.is_active ? 'Deactivate' : 'Reactivate'}</button>
          <button class="btn-danger btn-sm" onclick="deleteItem('stock-items', ${i.id}, loadStock)">Del</button>
        ` : ''}
      </td>
    </tr>`).join('');

  renderPagination('stock-pagination', data, loadStock);
}

document.getElementById('stock-search').addEventListener('input', e => {
  stockSearch = e.target.value;
  loadStock(1);
});

document.getElementById('btn-add-stock').addEventListener('click', () => openStockModal());

async function openStockModal(item = null) {
  const [suppliers, categories] = await Promise.all([
    apiFetch('/suppliers/?page_size=100'),
    apiFetch('/categories/?page_size=100')
  ]);
  const sups  = (suppliers && (suppliers.results || suppliers)) || [];
  const cats  = (categories && (categories.results || categories)) || [];

  openModal(item ? 'Edit Stock Item' : 'Add Stock Item', `
    <div class="form-row"><label>SKU *</label><input id="f-sku" value="${item?.sku||''}" placeholder="ELEC-001"/></div>
    <div class="form-row"><label>Name *</label><input id="f-name" value="${item?.name||''}" placeholder="Item name"/></div>
    <div class="form-row"><label>Description</label><textarea id="f-desc">${item?.description||''}</textarea></div>
    <div class="form-cols">
      <div class="form-row"><label>Category</label>
        <select id="f-category">
          <option value="">— None —</option>
          ${cats.map(c=>`<option value="${c.id}" ${item?.category==c.id?'selected':''}>${c.name}</option>`).join('')}
        </select>
      </div>
      <div class="form-row"><label>Supplier</label>
        <select id="f-supplier">
          <option value="">— None —</option>
          ${sups.map(s=>`<option value="${s.id}" ${item?.supplier==s.id?'selected':''}>${s.name}</option>`).join('')}
        </select>
      </div>
    </div>
    <div class="form-cols">
      <div class="form-row"><label>Unit Price *</label><input type="number" step="0.01" id="f-price" value="${item?.unit_price||''}" placeholder="0.00"/></div>
      <div class="form-row"><label>Qty in Stock</label><input type="number" id="f-qty" value="${item?.quantity_in_stock||0}"/></div>
    </div>
    <div class="form-cols">
      <div class="form-row"><label>Reorder Level</label><input type="number" id="f-reorder" value="${item?.reorder_level||10}"/></div>
      <div class="form-row"><label>Reorder Qty</label><input type="number" id="f-reorder-qty" value="${item?.reorder_quantity||50}"/></div>
    </div>
  `, async () => {
    const payload = {
      sku: document.getElementById('f-sku').value.trim(),
      name: document.getElementById('f-name').value.trim(),
      description: document.getElementById('f-desc').value.trim(),
      category: document.getElementById('f-category').value || null,
      supplier: document.getElementById('f-supplier').value || null,
      unit_price: document.getElementById('f-price').value,
      quantity_in_stock: document.getElementById('f-qty').value,
      reorder_level: document.getElementById('f-reorder').value,
      reorder_quantity: document.getElementById('f-reorder-qty').value,
      is_active: item ? item.is_active : true
    };
    if (!payload.sku || !payload.name || !payload.unit_price) { toast('SKU, Name and Price are required', 'error'); return; }
    const url    = item ? `/stock-items/${item.id}/` : '/stock-items/';
    const method = item ? 'PATCH' : 'POST';
    const res    = await apiFetch(url, { method, body: JSON.stringify(payload) });
    if (res && res.__ok) { closeModal(); toast(item ? 'Item updated' : 'Item created'); loadStock(stockPage); }
    else toast(firstApiError(res, 'Save failed'), 'error');
  });
}

async function editStockModal(id) {
  const item = await apiFetch(`/stock-items/${id}/`);
  if (item) openStockModal(item);
}

function adjustStockModal(id, name, current) {
  openModal(`Adjust Stock — ${name}`, `
    <p style="color:var(--gray-500);font-size:13px;margin-bottom:14px">Current quantity: <strong>${current}</strong></p>
    <div class="form-row"><label>Quantity Change *</label>
      <input type="number" id="f-adj-qty" placeholder="e.g. 10 to add, -5 to remove"/>
    </div>
    <div class="form-row"><label>Notes</label>
      <input id="f-adj-notes" placeholder="Reason for adjustment"/>
    </div>
  `, async () => {
    const qty   = document.getElementById('f-adj-qty').value;
    const notes = document.getElementById('f-adj-notes').value;
    if (!qty || qty == 0) { toast('Enter a non-zero quantity', 'error'); return; }
    const res = await apiFetch(`/stock-items/${id}/adjust_stock/`, {
      method: 'POST',
      body: JSON.stringify({ quantity: parseInt(qty), notes })
    });
    if (res && res.new_quantity !== undefined) {
      closeModal();
      toast(`Stock adjusted. New qty: ${res.new_quantity}`);
      loadStock(stockPage);
    } else toast(firstApiError(res, 'Adjustment failed'), 'error');
  });
}

// Deactivate/reactivate — the "safe delete" for items that have order
// history and can't be hard-deleted (StockItem.order_items is PROTECT).
async function toggleStockActive(id, currentlyActive) {
  const action = currentlyActive ? 'deactivate' : 'reactivate';
  const res = await apiFetch(`/stock-items/${id}/${action}/`, { method: 'POST' });
  if (res && res.is_active !== undefined) {
    toast(currentlyActive ? 'Item deactivated' : 'Item reactivated');
    loadStock(stockPage);
  } else {
    toast(firstApiError(res, 'Action failed'), 'error');
  }
}

// ────────────────────────────────────────────────────────
//  SUPPLIERS
// ────────────────────────────────────────────────────────
async function loadSuppliers() {
  const data = await apiFetch('/suppliers/?page_size=100');
  if (!data) return;
  const items = data.results || data;
  const tbody = document.getElementById('supplier-body');
  const staff = isStaff();

  if (!items.length) { tbody.innerHTML = '<tr><td colspan="6"><div class="empty-state">No suppliers yet</div></td></tr>'; return; }
  tbody.innerHTML = items.map(s => `
    <tr>
      <td><strong>${s.name}</strong></td>
      <td>${s.contact_name||'—'}</td>
      <td>${s.email||'—'}</td>
      <td>${s.phone||'—'}</td>
      <td>${s.is_active!==false ? '<span class="badge badge-success">Active</span>' : '<span class="badge badge-gray">Inactive</span>'}</td>
      <td class="td-actions">
        ${staff ? `
          <button class="btn-icon btn-sm" onclick="editSupplierModal(${s.id})">Edit</button>
          <button class="btn-danger btn-sm" onclick="deleteItem('suppliers', ${s.id}, loadSuppliers)">Del</button>
        ` : ''}
      </td>
    </tr>`).join('');
}

document.getElementById('btn-add-supplier').addEventListener('click', () => openSupplierModal());

function openSupplierModal(sup = null) {
  openModal(sup ? 'Edit Supplier' : 'Add Supplier', `
    <div class="form-row"><label>Name *</label><input id="f-sup-name" value="${sup?.name||''}" placeholder="Supplier Co. Ltd"/></div>
    <div class="form-cols">
      <div class="form-row"><label>Contact Name</label><input id="f-sup-contact" value="${sup?.contact_name||''}"/></div>
      <div class="form-row"><label>Phone</label><input id="f-sup-phone" value="${sup?.phone||''}" placeholder="+1-555-0101"/></div>
    </div>
    <div class="form-row"><label>Email</label><input type="email" id="f-sup-email" value="${sup?.email||''}" placeholder="orders@supplier.com"/></div>
    <div class="form-row"><label>Address</label><textarea id="f-sup-addr">${sup?.address||''}</textarea></div>
  `, async () => {
    const payload = {
      name: document.getElementById('f-sup-name').value.trim(),
      contact_name: document.getElementById('f-sup-contact').value.trim(),
      phone: document.getElementById('f-sup-phone').value.trim(),
      email: document.getElementById('f-sup-email').value.trim(),
      address: document.getElementById('f-sup-addr').value.trim(),
      is_active: true
    };
    if (!payload.name) { toast('Name is required', 'error'); return; }
    const url    = sup ? `/suppliers/${sup.id}/` : '/suppliers/';
    const method = sup ? 'PATCH' : 'POST';
    const res    = await apiFetch(url, { method, body: JSON.stringify(payload) });
    if (res && res.__ok) { closeModal(); toast(sup ? 'Supplier updated' : 'Supplier created'); loadSuppliers(); }
    else toast(firstApiError(res, 'Save failed'), 'error');
  });
}

async function editSupplierModal(id) {
  const sup = await apiFetch(`/suppliers/${id}/`);
  if (sup) openSupplierModal(sup);
}

// ────────────────────────────────────────────────────────
//  CATEGORIES
// ────────────────────────────────────────────────────────
async function loadCategories() {
  const data = await apiFetch('/categories/?page_size=100');
  if (!data) return;
  const items = data.results || data;
  const tbody = document.getElementById('category-body');
  const staff = isStaff();

  if (!items.length) { tbody.innerHTML = '<tr><td colspan="4"><div class="empty-state">No categories yet</div></td></tr>'; return; }
  tbody.innerHTML = items.map(c => `
    <tr>
      <td><strong>${c.name}</strong></td>
      <td>${c.description||'—'}</td>
      <td>${c.item_count ?? 0}</td>
      <td class="td-actions">
        ${staff ? `
          <button class="btn-icon btn-sm" onclick="editCategoryModal(${c.id})">Edit</button>
          <button class="btn-danger btn-sm" onclick="deleteItem('categories', ${c.id}, loadCategories)">Del</button>
        ` : ''}
      </td>
    </tr>`).join('');
}

document.getElementById('btn-add-category').addEventListener('click', () => openCategoryModal());

function openCategoryModal(cat = null) {
  openModal(cat ? 'Edit Category' : 'Add Category', `
    <div class="form-row"><label>Name *</label><input id="f-cat-name" value="${cat?.name||''}" placeholder="Electronics"/></div>
    <div class="form-row"><label>Description</label><textarea id="f-cat-desc">${cat?.description||''}</textarea></div>
  `, async () => {
    const payload = {
      name: document.getElementById('f-cat-name').value.trim(),
      description: document.getElementById('f-cat-desc').value.trim()
    };
    if (!payload.name) { toast('Name is required', 'error'); return; }
    const url    = cat ? `/categories/${cat.id}/` : '/categories/';
    const method = cat ? 'PATCH' : 'POST';
    const res    = await apiFetch(url, { method, body: JSON.stringify(payload) });
    if (res && res.__ok) { closeModal(); toast(cat ? 'Category updated' : 'Category created'); loadCategories(); }
    else toast(firstApiError(res, 'Save failed'), 'error');
  });
}

async function editCategoryModal(id) {
  const cat = await apiFetch(`/categories/${id}/`);
  if (cat) openCategoryModal(cat);
}

// ────────────────────────────────────────────────────────
//  ORDERS
// ────────────────────────────────────────────────────────
async function loadOrders() {
  const status = document.getElementById('order-status-filter').value;
  const type   = document.getElementById('order-type-filter').value;
  let url = '/orders/?ordering=-created_at';
  if (status) url += `&status=${status}`;
  if (type)   url += `&order_type=${type}`;

  const data = await apiFetch(url);
  if (!data) return;
  const items = data.results || data;
  const tbody = document.getElementById('order-body');
  const staff = isStaff();

  if (!items.length) { tbody.innerHTML = '<tr><td colspan="7"><div class="empty-state">No orders found</div></td></tr>'; return; }
  tbody.innerHTML = items.map(o => `
    <tr>
      <td><strong>${o.order_number}</strong></td>
      <td><span class="badge badge-blue">${o.order_type}</span></td>
      <td>${o.supplier_name||'—'}</td>
      <td>${statusBadge(o.status)}</td>
      <td>$${Number(o.total_amount||0).toFixed(2)}</td>
      <td>${new Date(o.created_at).toLocaleDateString()}</td>
      <td class="td-actions">
        ${staff ? `<button class="btn-icon btn-sm" onclick="updateOrderStatusModal(${o.id}, '${o.order_number}', '${o.status}', '${o.order_type}')">Status</button>` : ''}
        <button class="btn-icon btn-sm" onclick="viewOrderModal(${o.id})">View</button>
      </td>
    </tr>`).join('');
}

document.getElementById('order-status-filter').addEventListener('change', loadOrders);
document.getElementById('order-type-filter').addEventListener('change', loadOrders);

document.getElementById('btn-add-order').addEventListener('click', () => openOrderModal());

async function openOrderModal() {
  const [suppliers, items] = await Promise.all([
    apiFetch('/suppliers/?page_size=100'),
    apiFetch('/stock-items/?page_size=100')
  ]);
  const sups     = (suppliers && (suppliers.results || suppliers)) || [];
  const stockAll = (items && (items.results || items)) || [];

  openModal('New Purchase Order', `
    <div class="form-cols">
      <div class="form-row"><label>Order Type</label>
        <select id="f-ord-type">
          <option value="purchase">Purchase Order</option>
          <option value="sale">Sale Order</option>
        </select>
      </div>
      <div class="form-row"><label>Supplier</label>
        <select id="f-ord-supplier">
          <option value="">— None —</option>
          ${sups.map(s=>`<option value="${s.id}">${s.name}</option>`).join('')}
        </select>
      </div>
    </div>
    <div class="form-cols">
      <div class="form-row"><label>Expected Delivery</label><input type="date" id="f-ord-delivery"/></div>
    </div>
    <div class="form-row"><label>Notes</label><input id="f-ord-notes" placeholder="Optional notes"/></div>
    <div class="form-row">
      <label>Items *</label>
      <div id="order-items-container">
        <div class="order-item-row" style="display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:8px;margin-bottom:8px">
          <select class="oi-item"><option value="">— Select item —</option>${stockAll.map(s=>`<option value="${s.id}">${s.name}</option>`).join('')}</select>
          <input type="number" class="oi-qty" placeholder="Qty" min="1"/>
          <input type="number" class="oi-price" step="0.01" placeholder="Unit Price"/>
          <button type="button" onclick="this.closest('.order-item-row').remove()" style="background:none;border:none;color:var(--red);cursor:pointer;font-size:18px">×</button>
        </div>
      </div>
      <button type="button" id="btn-add-order-item" style="margin-top:6px;font-size:12px;padding:4px 10px;" class="btn-secondary">+ Add item</button>
    </div>
  `, async () => {
    const rows     = document.querySelectorAll('.order-item-row');
    const orderItems = [];
    rows.forEach(r => {
      const itemId = r.querySelector('.oi-item').value;
      const qty    = r.querySelector('.oi-qty').value;
      const price  = r.querySelector('.oi-price').value;
      if (itemId && qty && price) orderItems.push({ stock_item: parseInt(itemId), quantity: parseInt(qty), unit_price: price });
    });
    if (!orderItems.length) { toast('Add at least one item', 'error'); return; }
    const orderType = document.getElementById('f-ord-type').value;
    const supplier  = document.getElementById('f-ord-supplier').value || null;
    if (orderType === 'purchase' && !supplier) { toast('A supplier is required for purchase orders', 'error'); return; }
    const payload = {
      order_type: orderType,
      supplier: supplier,
      expected_delivery: document.getElementById('f-ord-delivery').value || null,
      notes: document.getElementById('f-ord-notes').value,
      items: orderItems
    };
    const res = await apiFetch('/orders/', { method: 'POST', body: JSON.stringify(payload) });
    if (res && res.__ok) { closeModal(); toast(`Order ${res.order_number} created`); loadOrders(); }
    else toast(firstApiError(res, 'Order creation failed'), 'error');
  });

  document.getElementById('btn-add-order-item').addEventListener('click', () => {
    const stockAll2 = stockAll;
    const row = document.createElement('div');
    row.className = 'order-item-row';
    row.style = 'display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:8px;margin-bottom:8px';
    row.innerHTML = `
      <select class="oi-item"><option value="">— Select item —</option>${stockAll2.map(s=>`<option value="${s.id}">${s.name}</option>`).join('')}</select>
      <input type="number" class="oi-qty" placeholder="Qty" min="1"/>
      <input type="number" class="oi-price" step="0.01" placeholder="Unit Price"/>
      <button type="button" onclick="this.closest('.order-item-row').remove()" style="background:none;border:none;color:var(--red);cursor:pointer;font-size:18px">×</button>`;
    document.getElementById('order-items-container').appendChild(row);
  });
}

// Status transitions now match the backend's actual STATUS_CHOICES and
// stock-moving rules: purchase orders move stock on "received", sale
// orders move stock on "shipped" — there is no "draft" status server-side.
function updateOrderStatusModal(id, number, current, orderType) {
  const transitions = {
    pending:   ['approved', 'cancelled'],
    approved:  ['shipped', 'cancelled'],
    shipped:   ['received', 'cancelled'],
    received:  [],
    cancelled: []
  };
  const allowed = transitions[current] || [];
  if (!allowed.length) { toast('No further status transitions available', 'info'); return; }

  let stockNote = '';
  if (orderType === 'purchase' && allowed.includes('received')) {
    stockNote = '<p style="font-size:12px;color:var(--blue);margin-top:8px">⚑ Marking as Received will add these items to stock.</p>';
  } else if (orderType === 'sale' && allowed.includes('shipped')) {
    stockNote = '<p style="font-size:12px;color:var(--blue);margin-top:8px">⚑ Marking as Shipped will deduct these items from stock — this will be rejected if there isn\'t enough stock on hand.</p>';
  }

  openModal(`Update Status — ${number}`, `
    <p style="color:var(--gray-500);font-size:13px;margin-bottom:14px">Current: ${statusBadge(current)}</p>
    <div class="form-row"><label>New Status</label>
      <select id="f-new-status">
        ${allowed.map(s=>`<option value="${s}">${s.charAt(0).toUpperCase()+s.slice(1)}</option>`).join('')}
      </select>
    </div>
    ${stockNote}
  `, async () => {
    const newStatus = document.getElementById('f-new-status').value;
    const res = await apiFetch(`/orders/${id}/update_status/`, {
      method: 'POST',
      body: JSON.stringify({ status: newStatus })
    });
    if (res && res.order_number) { closeModal(); toast(`Order status updated to ${newStatus}`); loadOrders(); loadDashboard(); }
    else toast(firstApiError(res, 'Update failed'), 'error');
  });
}

async function viewOrderModal(id) {
  const order = await apiFetch(`/orders/${id}/`);
  if (!order) return;
  openModal(`Order ${order.order_number}`, `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px">
      <div><span style="font-size:11px;color:var(--gray-500)">TYPE</span><br><strong>${order.order_type}</strong></div>
      <div><span style="font-size:11px;color:var(--gray-500)">STATUS</span><br>${statusBadge(order.status)}</div>
      <div><span style="font-size:11px;color:var(--gray-500)">SUPPLIER</span><br>${order.supplier_name||'—'}</div>
      <div><span style="font-size:11px;color:var(--gray-500)">CREATED</span><br>${new Date(order.created_at).toLocaleDateString()}</div>
    </div>
    <table style="width:100%;font-size:13px;border-collapse:collapse">
      <thead><tr style="background:var(--gray-50)"><th style="padding:8px;text-align:left">Item</th><th style="padding:8px;text-align:right">Qty</th><th style="padding:8px;text-align:right">Unit Price</th><th style="padding:8px;text-align:right">Subtotal</th></tr></thead>
      <tbody>${(order.items||[]).map(i=>`
        <tr style="border-top:1px solid var(--gray-100)">
          <td style="padding:8px">${i.item_name}</td>
          <td style="padding:8px;text-align:right">${i.quantity}</td>
          <td style="padding:8px;text-align:right">$${Number(i.unit_price).toFixed(2)}</td>
          <td style="padding:8px;text-align:right">$${Number(i.subtotal).toFixed(2)}</td>
        </tr>`).join('')}
      </tbody>
      <tfoot><tr style="border-top:2px solid var(--gray-200);font-weight:600">
        <td colspan="3" style="padding:8px;text-align:right">Total</td>
        <td style="padding:8px;text-align:right">$${Number(order.total_amount||0).toFixed(2)}</td>
      </tr></tfoot>
    </table>
  `, null);
  document.getElementById('modal-save').style.display = 'none';
}

// ────────────────────────────────────────────────────────
//  TRANSACTIONS
// ────────────────────────────────────────────────────────
async function loadTransactions() {
  const type = document.getElementById('txn-type-filter').value;
  let url = '/transactions/?ordering=-created_at';
  if (type) url += `&transaction_type=${type}`;

  const data = await apiFetch(url);
  if (!data) return;
  const items = data.results || data;
  const tbody = document.getElementById('txn-body');

  if (!items.length) { tbody.innerHTML = '<tr><td colspan="8"><div class="empty-state">No transactions</div></td></tr>'; return; }
  tbody.innerHTML = items.map(t => `
    <tr>
      <td>${t.stock_item_name}</td>
      <td><span class="sku-badge">${t.sku||''}</span></td>
      <td>${txnBadge(t.transaction_type)}</td>
      <td style="font-weight:600;color:${t.quantity>0?'var(--green)':'var(--red)'}">${t.quantity>0?'+':''}${t.quantity}</td>
      <td>${t.previous_quantity}</td>
      <td>${t.new_quantity}</td>
      <td>${t.notes||'—'}</td>
      <td>${new Date(t.created_at).toLocaleDateString()}</td>
    </tr>`).join('');
}

document.getElementById('txn-type-filter').addEventListener('change', loadTransactions);

// ────────────────────────────────────────────────────────
//  REPORTS
// ────────────────────────────────────────────────────────
let currentReportType = null;
let reportFiltersLoaded = false;

// Populates the category/supplier dropdowns once, the first time the
// Reports page is visited — no need to refetch on every report click.
async function populateReportFilters() {
  const [cats, sups] = await Promise.all([
    apiFetch('/categories/?page_size=100'),
    apiFetch('/suppliers/?page_size=100')
  ]);
  const catItems = (cats && (cats.results || cats)) || [];
  const supItems = (sups && (sups.results || sups)) || [];
  const catSel = document.getElementById('report-category');
  const supSel = document.getElementById('report-supplier');
  if (catSel) catSel.innerHTML = '<option value="">All categories</option>' + catItems.map(c=>`<option value="${c.id}">${c.name}</option>`).join('');
  if (supSel) supSel.innerHTML = '<option value="">All suppliers</option>' + supItems.map(s=>`<option value="${s.id}">${s.name}</option>`).join('');
}

// Only some filters make sense for some report types — dates are meaningless
// for a point-in-time stock summary, threshold only applies to low-stock.
function reportFilterConfig(type) {
  return {
    category:  ['stock-summary', 'reorder-alerts', 'low-stock', 'stock-valuation', 'transaction-history'].includes(type),
    supplier:  ['stock-summary', 'reorder-alerts', 'low-stock', 'stock-valuation', 'order-summary', 'transaction-history'].includes(type),
    dates:     ['order-summary', 'transaction-history'].includes(type),
    threshold: type === 'low-stock',
  };
}

function updateReportFilterVisibility(type) {
  const cfg = reportFilterConfig(type);
  document.getElementById('report-category').closest('#report-filter-bar')
    .querySelectorAll('.report-date-filter').forEach(el => el.style.display = cfg.dates ? '' : 'none');
  document.getElementById('report-threshold').style.display = cfg.threshold ? '' : 'none';
  document.getElementById('btn-export-report').style.display = '';
}

// Builds the query string from whichever filter inputs are relevant to
// this report type — same filters the backend's ReportView now accepts.
function buildReportQuery(type) {
  const cfg = reportFilterConfig(type);
  const params = new URLSearchParams();
  const category  = document.getElementById('report-category').value;
  const supplier  = document.getElementById('report-supplier').value;
  const startDate = document.getElementById('report-start-date').value;
  const endDate   = document.getElementById('report-end-date').value;
  const threshold = document.getElementById('report-threshold').value;

  if (cfg.category && category)   params.set('category', category);
  if (cfg.supplier && supplier)   params.set('supplier', supplier);
  if (cfg.dates && startDate)     params.set('start_date', startDate);
  if (cfg.dates && endDate)       params.set('end_date', endDate);
  if (cfg.threshold && threshold) params.set('threshold', threshold);
  return params.toString();
}

document.querySelectorAll('.report-card').forEach(card => {
  card.addEventListener('click', () => loadReport(card.dataset.report));
});

// Changing any filter re-runs whichever report is currently open.
['report-category', 'report-supplier', 'report-start-date', 'report-end-date', 'report-threshold'].forEach(id => {
  document.getElementById(id).addEventListener('change', () => {
    if (currentReportType) loadReport(currentReportType);
  });
});

document.getElementById('btn-export-report').addEventListener('click', () => {
  if (currentReportType) exportReportCSV(currentReportType);
});

// CSV export needs the auth header, so it can't be a plain <a href> link —
// fetch the file as a blob, then trigger the browser's save dialog manually.
async function exportReportCSV(type) {
  const qs = buildReportQuery(type);
  const url = `${API}/reports/${type}/?${qs ? qs + '&' : ''}export=csv`;
  try {
    const res = await fetch(url, { headers: authHeaders() });
    if (!res.ok) { toast('Export failed', 'error'); return; }
    const blob = await res.blob();
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${type}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(link.href);
  } catch (e) {
    toast('Export failed', 'error');
  }
}

async function loadReport(type) {
  currentReportType = type;
  updateReportFilterVisibility(type);

  const output = document.getElementById('report-output');
  output.classList.remove('hidden');
  output.innerHTML = '<div class="loading">Loading report…</div>';

  const qs = buildReportQuery(type);
  const data = await apiFetch(`/reports/${type}/${qs ? '?' + qs : ''}`);
  if (!data) { output.innerHTML = '<div class="empty-state">Failed to load report.</div>'; return; }

  const titles = {
    'stock-summary': 'Stock Summary',
    'reorder-alerts': 'Reorder Alerts',
    'stock-valuation': 'Stock Valuation',
    'order-summary': 'Order Summary',
    'low-stock': 'Low Stock Items',
    'transaction-history': 'Transaction History'
  };

  let html = `<h3>${titles[type]}</h3>`;

  if (type === 'stock-summary') {
    html += `
      <div class="report-stat-grid">
        <div class="report-stat"><div class="label">Total Items</div><div class="val">${data.total_active_items}</div></div>
        <div class="report-stat"><div class="label">Total Value</div><div class="val">$${Number(data.total_stock_value).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}</div></div>
        <div class="report-stat"><div class="label">Low Stock</div><div class="val" style="color:var(--amber)">${data.low_stock_items}</div></div>
        <div class="report-stat"><div class="label">Out of Stock</div><div class="val" style="color:var(--red)">${data.out_of_stock_items}</div></div>
      </div>
      <h4 style="font-size:13px;margin-bottom:10px;color:var(--gray-600)">By Category</h4>
      <table style="width:100%;border-collapse:collapse;font-size:13px">
        <thead><tr style="background:var(--gray-50)"><th style="padding:8px;text-align:left">Category</th><th style="padding:8px;text-align:right">Items</th><th style="padding:8px;text-align:right">Total Qty</th></tr></thead>
        <tbody>${(data.by_category||[]).map(c=>`<tr style="border-top:1px solid var(--gray-100)"><td style="padding:8px">${c.category__name||'Uncategorised'}</td><td style="padding:8px;text-align:right">${c.count}</td><td style="padding:8px;text-align:right">${c.total_qty}</td></tr>`).join('')}</tbody>
      </table>`;
  } else if (type === 'reorder-alerts') {
    html += `<div class="report-stat-grid"><div class="report-stat"><div class="label">Items needing reorder</div><div class="val" style="color:var(--amber)">${data.count}</div></div></div>`;
    html += `<table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="background:var(--gray-50)"><th style="padding:8px;text-align:left">SKU</th><th style="padding:8px;text-align:left">Name</th><th style="padding:8px;text-align:right">In Stock</th><th style="padding:8px;text-align:right">Reorder Level</th><th style="padding:8px;text-align:right">Shortage</th><th style="padding:8px;text-align:left">Supplier</th></tr></thead>
      <tbody>${(data.alerts||[]).map(a=>`<tr style="border-top:1px solid var(--gray-100)"><td style="padding:8px"><span class="sku-badge">${a.sku}</span></td><td style="padding:8px">${a.name}</td><td style="padding:8px;text-align:right;color:var(--red);font-weight:600">${a.quantity_in_stock}</td><td style="padding:8px;text-align:right">${a.reorder_level}</td><td style="padding:8px;text-align:right;color:var(--amber);font-weight:600">${a.shortage}</td><td style="padding:8px">${a.supplier||'—'}</td></tr>`).join('')}</tbody>
    </table>`;
  } else if (type === 'stock-valuation') {
    html += `<div class="report-stat-grid"><div class="report-stat"><div class="label">Total Inventory Value</div><div class="val">$${Number(data.total_valuation).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}</div></div></div>`;
    html += `<table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="background:var(--gray-50)"><th style="padding:8px;text-align:left">Category</th><th style="padding:8px;text-align:right">Items</th><th style="padding:8px;text-align:right">Value</th></tr></thead>
      <tbody>${Object.entries(data.by_category||{}).map(([cat,d])=>`<tr style="border-top:1px solid var(--gray-100)"><td style="padding:8px">${cat}</td><td style="padding:8px;text-align:right">${d.count}</td><td style="padding:8px;text-align:right;font-weight:600">$${Number(d.value).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}</td></tr>`).join('')}</tbody>
    </table>`;
  } else if (type === 'order-summary') {
    html += `<div class="report-stat-grid">
      <div class="report-stat"><div class="label">Total Orders</div><div class="val">${data.total_orders}</div></div>
      <div class="report-stat"><div class="label">Last 30 Days</div><div class="val">${data.orders_last_30_days}</div></div>
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="background:var(--gray-50)"><th style="padding:8px;text-align:left">Type</th><th style="padding:8px;text-align:left">Status</th><th style="padding:8px;text-align:right">Count</th></tr></thead>
      <tbody>${(data.by_status_and_type||[]).map(r=>`<tr style="border-top:1px solid var(--gray-100)"><td style="padding:8px">${r.order_type}</td><td style="padding:8px">${statusBadge(r.status)}</td><td style="padding:8px;text-align:right;font-weight:600">${r.count}</td></tr>`).join('')}</tbody>
    </table>`;
  } else if (type === 'low-stock') {
    html += `<div class="report-stat-grid"><div class="report-stat"><div class="label">Critical Items (≤${data.threshold})</div><div class="val" style="color:var(--red)">${data.count || (data.items||[]).length}</div></div></div>`;
    html += `<table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="background:var(--gray-50)"><th style="padding:8px;text-align:left">SKU</th><th style="padding:8px;text-align:left">Name</th><th style="padding:8px;text-align:right">In Stock</th><th style="padding:8px;text-align:right">Reorder Level</th></tr></thead>
      <tbody>${(data.items||[]).map(i=>`<tr style="border-top:1px solid var(--gray-100)"><td style="padding:8px"><span class="sku-badge">${i.sku}</span></td><td style="padding:8px">${i.name}</td><td style="padding:8px;text-align:right;color:var(--red);font-weight:600">${i.quantity_in_stock}</td><td style="padding:8px;text-align:right">${i.reorder_level}</td></tr>`).join('')}</tbody>
    </table>`;
  } else if (type === 'transaction-history') {
    html += `<table style="width:100%;border-collapse:collapse;font-size:13px">
      <thead><tr style="background:var(--gray-50)"><th style="padding:8px;text-align:left">Type</th><th style="padding:8px;text-align:right">Count</th><th style="padding:8px;text-align:right">Total Qty</th></tr></thead>
      <tbody>${(data.summary||[]).map(r=>`<tr style="border-top:1px solid var(--gray-100)"><td style="padding:8px">${txnBadge(r.transaction_type)}</td><td style="padding:8px;text-align:right">${r.count}</td><td style="padding:8px;text-align:right;font-weight:600">${r.total_qty}</td></tr>`).join('')}</tbody>
    </table>`;
  }

  output.innerHTML = html;
}

// ────────────────────────────────────────────────────────
//  SHARED HELPERS
// ────────────────────────────────────────────────────────
function statusBadge(s) {
  const map = {
    pending:   'badge-warn',
    approved:  'badge-blue',
    shipped:   'badge-purple',
    received:  'badge-success',
    cancelled: 'badge-danger',
    active:    'badge-success',
    inactive:  'badge-gray'
  };
  return `<span class="badge ${map[s]||'badge-gray'}">${s}</span>`;
}

function txnBadge(t) {
  const map = { in: 'badge-success', out: 'badge-danger', adjustment: 'badge-warn' };
  return `<span class="badge ${map[t]||'badge-gray'}">${t.replace(/_/g,' ')}</span>`;
}

function renderPagination(containerId, data, loadFn) {
  const container = document.getElementById(containerId);
  if (!container) return;
  if (!data.count || !data.next && !data.previous) { container.innerHTML = ''; return; }
  const pageSize  = 20;
  const total     = Math.ceil(data.count / pageSize);
  let html = '';
  for (let i = 1; i <= total; i++) {
    html += `<button class="${i===stockPage?'active':''}" onclick="loadStock(${i})">${i}</button>`;
  }
  container.innerHTML = html;
}

async function deleteItem(resource, id, reloadFn) {
  if (!confirm('Delete this item? This cannot be undone.')) return;
  const res = await apiFetch(`/${resource}/${id}/`, { method: 'DELETE' });
  // res.__ok reflects the real HTTP status now — a 409 (item referenced by
  // an order) previously looked "successful" here because it still parsed
  // as JSON. Now we check the actual outcome and show the real reason.
  if (res && res.__ok) { toast('Deleted successfully'); reloadFn(); }
  else toast(firstApiError(res, 'Delete failed'), 'error');
}

// ────────────────────────────────────────────────────────
//  MODAL
// ────────────────────────────────────────────────────────
let modalSaveFn = null;

function openModal(title, bodyHtml, saveFn) {
  document.getElementById('modal-title').textContent = title;
  document.getElementById('modal-body').innerHTML = bodyHtml;
  document.getElementById('modal-overlay').classList.remove('hidden');
  const saveBtn = document.getElementById('modal-save');
  saveBtn.style.display = saveFn ? '' : 'none';
  modalSaveFn = saveFn;
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
  modalSaveFn = null;
}

document.getElementById('modal-close').addEventListener('click', closeModal);
document.getElementById('modal-cancel').addEventListener('click', closeModal);
document.getElementById('modal-save').addEventListener('click', () => { if (modalSaveFn) modalSaveFn(); });
document.getElementById('modal-overlay').addEventListener('click', e => { if (e.target === e.currentTarget) closeModal(); });