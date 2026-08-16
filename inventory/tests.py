"""
Automated tests for the inventory API.

Covers every improvement made across items #1-#6:
  - AuthTests                : login/refresh/logout, token blacklisting
  - ValidationTests           : #1 — SKU/price/field/quantity validation
  - StockAdjustmentTests      : #2 — stock can't go negative
  - PermissionTests           : #3 — staff-only writes, read access for all
  - DeleteProtectionTests     : bug fix — 409 instead of 500, deactivate/reactivate
  - OrderWorkflowTests        : #4 — valid status transition graph
  - OrderStockMovementTests   : #2/#5 — receive/ship/cancel stock movement
  - ReportTests               : #6 — filters and CSV export

Run with:  python manage.py test inventory
"""
from decimal import Decimal

from django.contrib.auth.models import User
from rest_framework import status
from rest_framework.test import APITestCase

from .models import Supplier, Category, StockItem, Order, OrderItem, StockTransaction


class BaseAPITestCase(APITestCase):
    """Common fixtures shared by every test class below."""

    def setUp(self):
        self.staff_user = User.objects.create_user(
            username='staffuser', password='TestPass123!', is_staff=True
        )
        self.regular_user = User.objects.create_user(
            username='regularuser', password='TestPass123!', is_staff=False
        )

        self.supplier = Supplier.objects.create(name='Acme Supplies', email='acme@example.com')
        self.category = Category.objects.create(name='Electronics')

        self.item = StockItem.objects.create(
            sku='ELEC-001', name='Widget', category=self.category, supplier=self.supplier,
            unit_price=Decimal('10.00'), quantity_in_stock=50,
            reorder_level=10, reorder_quantity=20,
        )

    def auth_as_staff(self):
        self.client.force_authenticate(user=self.staff_user)

    def auth_as_regular(self):
        self.client.force_authenticate(user=self.regular_user)


# ─── Auth: login, refresh, logout ──────────────────────────────────────────

class AuthTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='alice', password='TestPass123!', is_staff=True)

    def test_login_returns_tokens_and_user_info(self):
        res = self.client.post('/api/auth/login/', {'username': 'alice', 'password': 'TestPass123!'})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('access', res.data)
        self.assertIn('refresh', res.data)
        self.assertEqual(res.data['user']['username'], 'alice')
        self.assertTrue(res.data['user']['is_staff'])

    def test_login_wrong_password_rejected(self):
        res = self.client.post('/api/auth/login/', {'username': 'alice', 'password': 'wrong'})
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_refresh_returns_new_access_token(self):
        login = self.client.post('/api/auth/login/', {'username': 'alice', 'password': 'TestPass123!'})
        refresh_token = login.data['refresh']
        res = self.client.post('/api/auth/refresh/', {'refresh': refresh_token})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('access', res.data)

    def test_logout_blacklists_refresh_token(self):
        login = self.client.post('/api/auth/login/', {'username': 'alice', 'password': 'TestPass123!'})
        access_token = login.data['access']
        refresh_token = login.data['refresh']

        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access_token}')
        logout_res = self.client.post('/api/auth/logout/', {'refresh': refresh_token})
        self.assertEqual(logout_res.status_code, status.HTTP_205_RESET_CONTENT)

        # The blacklisted refresh token must no longer work.
        retry = self.client.post('/api/auth/refresh/', {'refresh': refresh_token})
        self.assertEqual(retry.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_without_refresh_token_returns_400(self):
        login = self.client.post('/api/auth/login/', {'username': 'alice', 'password': 'TestPass123!'})
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {login.data["access"]}')
        res = self.client.post('/api/auth/logout/', {})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


# ─── #1: Validation ─────────────────────────────────────────────────────────

class ValidationTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.auth_as_staff()

    def test_duplicate_sku_rejected(self):
        res = self.client.post('/api/stock-items/', {
            'sku': 'elec-001',  # same as fixture item, different case
            'name': 'Duplicate Widget',
            'unit_price': '5.00',
            'quantity_in_stock': 10,
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('sku', res.data)

    def test_zero_price_rejected(self):
        res = self.client.post('/api/stock-items/', {
            'sku': 'NEW-001', 'name': 'Freebie', 'unit_price': '0.00', 'quantity_in_stock': 10,
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('unit_price', res.data)

    def test_negative_quantity_rejected(self):
        res = self.client.post('/api/stock-items/', {
            'sku': 'NEW-002', 'name': 'Bad Qty', 'unit_price': '5.00', 'quantity_in_stock': -5,
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('quantity_in_stock', res.data)

    def test_missing_required_fields_rejected(self):
        res = self.client.post('/api/stock-items/', {'description': 'no sku, no name, no price'})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('sku', res.data)
        self.assertIn('name', res.data)
        self.assertIn('unit_price', res.data)

    def test_reorder_quantity_must_be_positive(self):
        res = self.client.post('/api/stock-items/', {
            'sku': 'NEW-003', 'name': 'Bad Reorder', 'unit_price': '5.00',
            'quantity_in_stock': 10, 'reorder_quantity': 0,
        })
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_valid_item_created_successfully(self):
        res = self.client.post('/api/stock-items/', {
            'sku': 'NEW-004', 'name': 'Good Widget', 'unit_price': '12.50', 'quantity_in_stock': 25,
        })
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data['sku'], 'NEW-004')


# ─── #2: Stock can't go negative ───────────────────────────────────────────

class StockAdjustmentTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.auth_as_staff()

    def test_positive_adjustment_increases_stock(self):
        res = self.client.post(f'/api/stock-items/{self.item.id}/adjust_stock/', {'quantity': 10})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['new_quantity'], 60)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, 60)

    def test_adjustment_cannot_take_stock_below_zero(self):
        res = self.client.post(f'/api/stock-items/{self.item.id}/adjust_stock/', {'quantity': -999})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, 50)  # unchanged

    def test_zero_adjustment_rejected(self):
        res = self.client.post(f'/api/stock-items/{self.item.id}/adjust_stock/', {'quantity': 0})
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_adjustment_creates_stock_transaction(self):
        self.client.post(f'/api/stock-items/{self.item.id}/adjust_stock/', {'quantity': -5, 'notes': 'damaged'})
        txn = StockTransaction.objects.filter(stock_item=self.item).latest('created_at')
        self.assertEqual(txn.quantity, -5)
        self.assertEqual(txn.transaction_type, 'out')
        self.assertEqual(txn.previous_quantity, 50)
        self.assertEqual(txn.new_quantity, 45)


# ─── #3: Permissions ────────────────────────────────────────────────────────

class PermissionTests(BaseAPITestCase):
    def test_regular_user_can_read_stock_items(self):
        self.auth_as_regular()
        res = self.client.get('/api/stock-items/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_regular_user_cannot_create_stock_item(self):
        self.auth_as_regular()
        res = self.client.post('/api/stock-items/', {
            'sku': 'BLOCKED-001', 'name': 'Should Fail', 'unit_price': '5.00', 'quantity_in_stock': 1,
        })
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_regular_user_cannot_delete_supplier(self):
        self.auth_as_regular()
        res = self.client.delete(f'/api/suppliers/{self.supplier.id}/')
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_user_can_create_supplier(self):
        self.auth_as_staff()
        res = self.client.post('/api/suppliers/', {'name': 'New Supplier Co'})
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    def test_unauthenticated_request_rejected(self):
        res = self.client.get('/api/stock-items/')
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)


# ─── Delete protection / deactivate-reactivate ─────────────────────────────

class DeleteProtectionTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.auth_as_staff()
        order = Order.objects.create(order_type='purchase', supplier=self.supplier, created_by=self.staff_user)
        OrderItem.objects.create(order=order, stock_item=self.item, quantity=5, unit_price=Decimal('10.00'))

    def test_deleting_referenced_item_returns_409_not_500(self):
        res = self.client.delete(f'/api/stock-items/{self.item.id}/')
        self.assertEqual(res.status_code, status.HTTP_409_CONFLICT)
        self.assertIn('error', res.data)
        self.assertIn('suggestion', res.data)
        self.assertTrue(StockItem.objects.filter(pk=self.item.id).exists())  # not deleted

    def test_deactivate_and_reactivate(self):
        res = self.client.post(f'/api/stock-items/{self.item.id}/deactivate/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.item.refresh_from_db()
        self.assertFalse(self.item.is_active)

        res = self.client.post(f'/api/stock-items/{self.item.id}/reactivate/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.item.refresh_from_db()
        self.assertTrue(self.item.is_active)

    def test_unreferenced_item_deletes_normally(self):
        free_item = StockItem.objects.create(
            sku='FREE-001', name='Never Ordered', unit_price=Decimal('1.00'), quantity_in_stock=1
        )
        res = self.client.delete(f'/api/stock-items/{free_item.id}/')
        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)


# ─── #4: Order status transition graph ─────────────────────────────────────

class OrderWorkflowTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.auth_as_staff()
        self.purchase_order = Order.objects.create(
            order_type='purchase', supplier=self.supplier, created_by=self.staff_user
        )
        OrderItem.objects.create(order=self.purchase_order, stock_item=self.item, quantity=10, unit_price=Decimal('10.00'))

    def _set_status(self, order, new_status):
        return self.client.post(f'/api/orders/{order.id}/update_status/', {'status': new_status})

    def test_valid_transition_pending_to_approved(self):
        res = self._set_status(self.purchase_order, 'approved')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['status'], 'approved')

    def test_cannot_skip_straight_to_received(self):
        res = self._set_status(self.purchase_order, 'received')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('allowed_next_statuses', res.data)
        self.purchase_order.refresh_from_db()
        self.assertEqual(self.purchase_order.status, 'pending')  # unchanged

    def test_cannot_transition_from_terminal_state(self):
        self._set_status(self.purchase_order, 'cancelled')
        res = self._set_status(self.purchase_order, 'approved')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_status_field_is_read_only_on_regular_serializer(self):
        """PATCHing status directly must be ignored — only update_status can change it."""
        res = self.client.patch(f'/api/orders/{self.purchase_order.id}/', {'status': 'received'}, format='json')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.purchase_order.refresh_from_db()
        self.assertEqual(self.purchase_order.status, 'pending')  # unchanged despite the request

    def test_items_locked_after_order_leaves_pending(self):
        self._set_status(self.purchase_order, 'approved')
        other_item = StockItem.objects.create(sku='OTHER-001', name='Other', unit_price=Decimal('1.00'))
        res = self.client.patch(
            f'/api/orders/{self.purchase_order.id}/',
            {'items': [{'stock_item': other_item.id, 'quantity': 1, 'unit_price': '1.00'}]},
            format='json'
        )
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


# ─── #2/#5: Stock movement on receive / ship / cancel ──────────────────────

class OrderStockMovementTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.auth_as_staff()

    def _set_status(self, order, new_status):
        return self.client.post(f'/api/orders/{order.id}/update_status/', {'status': new_status})

    def test_purchase_received_adds_stock(self):
        order = Order.objects.create(order_type='purchase', supplier=self.supplier, created_by=self.staff_user)
        OrderItem.objects.create(order=order, stock_item=self.item, quantity=20, unit_price=Decimal('10.00'))

        self._set_status(order, 'approved')
        self._set_status(order, 'shipped')
        res = self._set_status(order, 'received')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, 70)  # 50 + 20

    def test_sale_shipped_deducts_stock(self):
        order = Order.objects.create(order_type='sale', created_by=self.staff_user)
        OrderItem.objects.create(order=order, stock_item=self.item, quantity=15, unit_price=Decimal('10.00'))

        self._set_status(order, 'approved')
        res = self._set_status(order, 'shipped')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, 35)  # 50 - 15

    def test_sale_shipped_rejected_when_insufficient_stock(self):
        order = Order.objects.create(order_type='sale', created_by=self.staff_user)
        OrderItem.objects.create(order=order, stock_item=self.item, quantity=999, unit_price=Decimal('10.00'))

        self._set_status(order, 'approved')
        res = self._set_status(order, 'shipped')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('shortages', res.data)
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, 50)  # unchanged

    def test_cancel_sale_order_before_shipping_does_not_touch_stock(self):
        order = Order.objects.create(order_type='sale', created_by=self.staff_user)
        OrderItem.objects.create(order=order, stock_item=self.item, quantity=10, unit_price=Decimal('10.00'))

        self._set_status(order, 'approved')
        self._set_status(order, 'cancelled')

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, 50)  # unchanged — never shipped

    def test_cancel_sale_order_after_shipping_reverses_stock(self):
        order = Order.objects.create(order_type='sale', created_by=self.staff_user)
        OrderItem.objects.create(order=order, stock_item=self.item, quantity=10, unit_price=Decimal('10.00'))

        self._set_status(order, 'approved')
        self._set_status(order, 'shipped')
        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, 40)  # deducted

        res = self._set_status(order, 'cancelled')
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        self.item.refresh_from_db()
        self.assertEqual(self.item.quantity_in_stock, 50)  # reversed back

        reversal_txn = StockTransaction.objects.filter(order=order, transaction_type='in').latest('created_at')
        self.assertEqual(reversal_txn.quantity, 10)

    def test_cannot_cancel_purchase_order_after_received(self):
        order = Order.objects.create(order_type='purchase', supplier=self.supplier, created_by=self.staff_user)
        OrderItem.objects.create(order=order, stock_item=self.item, quantity=5, unit_price=Decimal('10.00'))
        self._set_status(order, 'approved')
        self._set_status(order, 'shipped')
        self._set_status(order, 'received')

        res = self._set_status(order, 'cancelled')
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)


# ─── #6: Report filters and CSV export ─────────────────────────────────────

class ReportTests(BaseAPITestCase):
    def setUp(self):
        super().setUp()
        self.auth_as_staff()
        self.other_category = Category.objects.create(name='Furniture')
        StockItem.objects.create(
            sku='FURN-001', name='Chair', category=self.other_category,
            unit_price=Decimal('40.00'), quantity_in_stock=3, reorder_level=10,  # triggers reorder alert
        )

    def test_stock_summary_report(self):
        res = self.client.get('/api/reports/stock-summary/')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn('total_active_items', res.data)

    def test_reorder_alerts_filtered_by_category(self):
        res = self.client.get(f'/api/reports/reorder-alerts/?category={self.other_category.id}')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['count'], 1)
        self.assertEqual(res.data['alerts'][0]['sku'], 'FURN-001')

    def test_low_stock_custom_threshold(self):
        res = self.client.get('/api/reports/low-stock/?threshold=4')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        skus = [i['sku'] for i in res.data['items']]
        self.assertIn('FURN-001', skus)
        self.assertNotIn('ELEC-001', skus)  # has 50 in stock, above threshold

    def test_csv_export_returns_csv_content_type(self):
        res = self.client.get('/api/reports/stock-summary/?export=csv')
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], 'text/csv')
        self.assertIn('attachment', res['Content-Disposition'])

    def test_unknown_report_type_returns_404(self):
        res = self.client.get('/api/reports/not-a-real-report/')
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)