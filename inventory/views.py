from rest_framework import viewsets, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAdminUser, IsAuthenticated, AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum, F, Count, Q
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from django.utils import timezone
from datetime import timedelta, datetime
import csv
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from .models import Supplier, Category, StockItem, Order, OrderItem, StockTransaction
from .permissions import IsStaffOrReadOnly
from .serializers import (
    UserSerializer, SupplierSerializer, CategorySerializer,
    StockItemSerializer, StockItemListSerializer, StockAdjustmentSerializer,
    OrderSerializer, OrderListSerializer,
    StockTransactionSerializer, MyTokenObtainPairSerializer,
)


# ─── Auth ────────────────────────────────────────────────────────────────────

class RegisterView(generics.CreateAPIView):
    """Admin-only user registration."""
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminUser]


class ProfileView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user


class MyTokenObtainPairView(TokenObtainPairView):
    """Login view — same endpoint, but the response includes user/role info."""
    serializer_class = MyTokenObtainPairSerializer
    throttle_scope = 'login'


class LogoutView(generics.GenericAPIView):
    """
    Blacklists the given refresh token so it (and any access token later
    minted from it) can no longer be used. Requires
    'rest_framework_simplejwt.token_blacklist' in INSTALLED_APPS and its
    migrations applied.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {'error': 'A "refresh" token is required to log out.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            return Response(
                {'error': 'Refresh token is invalid or already expired/blacklisted.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        return Response({'detail': 'Successfully logged out.'}, status=status.HTTP_205_RESET_CONTENT)


# ─── Suppliers ───────────────────────────────────────────────────────────────

class SupplierViewSet(viewsets.ModelViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated, IsStaffOrReadOnly]
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'contact_name', 'email']
    ordering_fields = ['name', 'created_at']

    @action(detail=True, methods=['get'])
    def items(self, request, pk=None):
        supplier = self.get_object()
        items = supplier.items.filter(is_active=True)
        serializer = StockItemListSerializer(items, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def orders(self, request, pk=None):
        supplier = self.get_object()
        orders = supplier.orders.all()
        serializer = OrderListSerializer(orders, many=True)
        return Response(serializer.data)


# ─── Categories ──────────────────────────────────────────────────────────────

class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated, IsStaffOrReadOnly]
    filter_backends = [SearchFilter]
    search_fields = ['name']


# ─── Stock Items ─────────────────────────────────────────────────────────────

class StockItemViewSet(viewsets.ModelViewSet):
    queryset = StockItem.objects.select_related('category', 'supplier').all()
    permission_classes = [IsAuthenticated, IsStaffOrReadOnly]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['category', 'supplier', 'is_active', 'unit']
    search_fields = ['name', 'sku', 'description']
    ordering_fields = ['name', 'quantity_in_stock', 'unit_price', 'created_at']

    def get_serializer_class(self):
        if self.action == 'list':
            return StockItemListSerializer
        return StockItemSerializer

    def destroy(self, request, *args, **kwargs):
        """
        StockItem.order_items uses on_delete=PROTECT, so any item that's
        ever appeared on an order can't be hard-deleted — Django raises
        ProtectedError, which is otherwise an unhandled 500. Catch it and
        point the caller at the real fix: deactivate instead of delete.
        """
        item = self.get_object()
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError:
            return Response(
                {
                    'error': (
                        f"Cannot delete '{item.name}' ({item.sku}): it appears on one or more "
                        "orders and deleting it would break that order history."
                    ),
                    'suggestion': (
                        "Set is_active=False instead (PATCH this item with "
                        '{"is_active": false}) to hide it from active use without losing history.'
                    ),
                },
                status=status.HTTP_409_CONFLICT
            )

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Soft-delete: hide from active use without touching order history."""
        item = self.get_object()
        if not item.is_active:
            return Response(
                {'sku': item.sku, 'name': item.name, 'is_active': False, 'detail': 'Already inactive.'}
            )
        item.is_active = False
        item.save(update_fields=['is_active', 'updated_at'])
        return Response({'sku': item.sku, 'name': item.name, 'is_active': item.is_active})

    @action(detail=True, methods=['post'])
    def reactivate(self, request, pk=None):
        """Undo deactivate — bring the item back into active use."""
        item = self.get_object()
        if item.is_active:
            return Response(
                {'sku': item.sku, 'name': item.name, 'is_active': True, 'detail': 'Already active.'}
            )
        item.is_active = True
        item.save(update_fields=['is_active', 'updated_at'])
        return Response({'sku': item.sku, 'name': item.name, 'is_active': item.is_active})

    @action(detail=True, methods=['post'])
    def adjust_stock(self, request, pk=None):
        """
        Manually adjust stock quantity (positive = add, negative = remove).

        Runs inside a locked transaction so two concurrent adjustments on the
        same item can never both read the same "before" quantity and push
        stock negative — the second request always sees the first one's result.
        """
        # get_object() gives us the standard 404 (invalid pk) and runs any
        # object-level permission checks before we touch the database.
        self.get_object()

        serializer = StockAdjustmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        quantity = serializer.validated_data['quantity']
        notes = serializer.validated_data.get('notes', '')

        with transaction.atomic():
            # Re-fetch the same row locked, so a concurrent adjust_stock
            # call on the same item has to wait instead of racing against
            # a quantity that get_object() already read a moment ago.
            item = StockItem.objects.select_for_update().get(pk=pk)

            previous_qty = item.quantity_in_stock
            new_qty = previous_qty + quantity

            if new_qty < 0:
                return Response(
                    {
                        'error': 'Insufficient stock for this adjustment.',
                        'available': previous_qty,
                        'requested_change': quantity,
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            item.quantity_in_stock = new_qty
            item.save(update_fields=['quantity_in_stock', 'updated_at'])

            StockTransaction.objects.create(
                stock_item=item,
                transaction_type='in' if quantity > 0 else 'out',
                quantity=quantity,
                previous_quantity=previous_qty,
                new_quantity=new_qty,
                notes=notes,
                created_by=request.user,
            )

        return Response({
            'sku': item.sku,
            'name': item.name,
            'previous_quantity': previous_qty,
            'adjusted_by': quantity,
            'new_quantity': new_qty,
            'needs_reorder': item.needs_reorder,
        })

    @action(detail=True, methods=['get'])
    def transactions(self, request, pk=None):
        item = self.get_object()
        txns = item.transactions.all()
        serializer = StockTransactionSerializer(txns, many=True)
        return Response(serializer.data)


# ─── Orders ──────────────────────────────────────────────────────────────────

# The valid status graph. Split by order_type because they move stock at
# different points (#2): purchase orders take stock IN on 'received', sale
# orders take stock OUT on 'shipped'. Once stock has moved for an order,
# 'cancelled' is deliberately removed from its allowed next-states here —
# reversing already-moved stock on cancellation is a bigger, separate piece
# of work (see item #5) and shouldn't be silently half-implemented here.
ORDER_STATUS_TRANSITIONS = {
    'purchase': {
        'pending':   {'approved', 'cancelled'},
        'approved':  {'shipped', 'cancelled'},
        'shipped':   {'received', 'cancelled'},  # stock hasn't moved yet — safe to cancel
        'received':  set(),                      # terminal — stock already added
        'cancelled': set(),                       # terminal
    },
    'sale': {
        'pending':   {'approved', 'cancelled'},
        'approved':  {'shipped', 'cancelled'},    # stock hasn't moved yet — safe to cancel
        'shipped':   {'received', 'cancelled'},   # cancelling here reverses the stock deduction (see #5)
        'received':  set(),                       # terminal
        'cancelled': set(),                        # terminal
    },
}


class OrderViewSet(viewsets.ModelViewSet):
    queryset = Order.objects.prefetch_related('items__stock_item').select_related('supplier', 'created_by').all()
    permission_classes = [IsAuthenticated, IsStaffOrReadOnly]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['status', 'order_type', 'supplier']
    search_fields = ['order_number', 'notes']
    ordering_fields = ['created_at', 'expected_delivery']

    def get_serializer_class(self):
        if self.action == 'list':
            return OrderListSerializer
        return OrderSerializer

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def update_status(self, request, pk=None):
        """
        Transition an order's status through the valid workflow graph
        (ORDER_STATUS_TRANSITIONS): pending -> approved -> shipped -> received,
        with cancellation only available before stock has actually moved.

        Stock-moving transitions run inside a locked transaction, every
        affected StockItem row locked and checked up front:
          - purchase order -> received:  stock IN
          - sale order     -> shipped:   stock OUT (rejected if insufficient)
          - sale order (already shipped) -> cancelled: stock IN (reversal —
            the shipment never completed, so what left the warehouse comes
            back)
        This means an order can never partially move stock and fail
        halfway through, and stock can never go negative.
        """
        # get_object() gives us the standard 404 (invalid pk) and runs any
        # object-level permission checks before we touch the database.
        self.get_object()

        new_status = request.data.get('status')
        valid = [s[0] for s in Order.STATUS_CHOICES]

        if new_status not in valid:
            return Response(
                {'error': f'Invalid status. Choose from: {valid}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        with transaction.atomic():
            # Lock the order row itself so two simultaneous status-change
            # requests for the same order can't both act on the old status.
            order = Order.objects.select_for_update().get(pk=pk)
            old_status = order.status

            if old_status == new_status:
                return Response({'order_number': order.order_number, 'status': order.status})

            transitions = ORDER_STATUS_TRANSITIONS.get(order.order_type, {})
            allowed_next = transitions.get(old_status, set())

            if new_status not in allowed_next:
                return Response(
                    {
                        'error': f"Cannot move a {order.order_type} order from '{old_status}' to '{new_status}'.",
                        'current_status': old_status,
                        'allowed_next_statuses': sorted(allowed_next) if allowed_next else [],
                        'detail': (
                            "This order is in a terminal state." if not allowed_next
                            else f"From '{old_status}', this order can only move to: {sorted(allowed_next)}."
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )

            order_items = list(order.items.select_related('stock_item'))

            # Purchase order received → stock comes IN. Can't go negative,
            # so no availability check is needed, but we still lock the rows
            # for consistency with the sale-order path below.
            if new_status == 'received' and old_status != 'received' and order.order_type == 'purchase':
                item_ids = [oi.stock_item_id for oi in order_items]
                locked_items = {
                    si.pk: si for si in StockItem.objects.select_for_update().filter(pk__in=item_ids)
                }
                for oi in order_items:
                    stock_item = locked_items[oi.stock_item_id]
                    prev_qty = stock_item.quantity_in_stock
                    stock_item.quantity_in_stock = prev_qty + oi.quantity
                    stock_item.save(update_fields=['quantity_in_stock', 'updated_at'])
                    StockTransaction.objects.create(
                        stock_item=stock_item,
                        transaction_type='in',
                        quantity=oi.quantity,
                        previous_quantity=prev_qty,
                        new_quantity=stock_item.quantity_in_stock,
                        order=order,
                        notes=f'Received via order {order.order_number}',
                        created_by=request.user,
                    )

            # Sale order shipped → stock goes OUT. Must never go negative.
            # Every line item is checked against the locked, up-to-date
            # quantity before ANY item is deducted, so the order either
            # fully succeeds or fully fails — never a partial shipment.
            elif new_status == 'shipped' and old_status != 'shipped' and order.order_type == 'sale':
                item_ids = [oi.stock_item_id for oi in order_items]
                locked_items = {
                    si.pk: si for si in StockItem.objects.select_for_update().filter(pk__in=item_ids)
                }

                shortages = []
                for oi in order_items:
                    stock_item = locked_items[oi.stock_item_id]
                    if stock_item.quantity_in_stock < oi.quantity:
                        shortages.append({
                            'sku': stock_item.sku,
                            'name': stock_item.name,
                            'available': stock_item.quantity_in_stock,
                            'requested': oi.quantity,
                        })

                if shortages:
                    return Response(
                        {
                            'error': 'Cannot ship order: insufficient stock for one or more items.',
                            'shortages': shortages,
                        },
                        status=status.HTTP_400_BAD_REQUEST
                    )

                for oi in order_items:
                    stock_item = locked_items[oi.stock_item_id]
                    prev_qty = stock_item.quantity_in_stock
                    stock_item.quantity_in_stock = prev_qty - oi.quantity
                    stock_item.save(update_fields=['quantity_in_stock', 'updated_at'])
                    StockTransaction.objects.create(
                        stock_item=stock_item,
                        transaction_type='out',
                        quantity=-oi.quantity,
                        previous_quantity=prev_qty,
                        new_quantity=stock_item.quantity_in_stock,
                        order=order,
                        notes=f'Shipped via order {order.order_number}',
                        created_by=request.user,
                    )

            # Cancelling a sale order that already shipped: the stock that
            # left the warehouse for this order comes back. No shortage
            # check needed here — we're adding stock, not removing it — but
            # we still lock the rows for consistency and to avoid a lost
            # update if something else is touching the same items.
            elif new_status == 'cancelled' and old_status == 'shipped' and order.order_type == 'sale':
                item_ids = [oi.stock_item_id for oi in order_items]
                locked_items = {
                    si.pk: si for si in StockItem.objects.select_for_update().filter(pk__in=item_ids)
                }
                for oi in order_items:
                    stock_item = locked_items[oi.stock_item_id]
                    prev_qty = stock_item.quantity_in_stock
                    stock_item.quantity_in_stock = prev_qty + oi.quantity
                    stock_item.save(update_fields=['quantity_in_stock', 'updated_at'])
                    StockTransaction.objects.create(
                        stock_item=stock_item,
                        transaction_type='in',
                        quantity=oi.quantity,
                        previous_quantity=prev_qty,
                        new_quantity=stock_item.quantity_in_stock,
                        order=order,
                        notes=f'Reversed — order {order.order_number} cancelled after shipment',
                        created_by=request.user,
                    )

            order.status = new_status
            order.save(update_fields=['status', 'updated_at'])

        return Response({'order_number': order.order_number, 'status': order.status})


# ─── Stock Transactions ───────────────────────────────────────────────────────

class StockTransactionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = StockTransaction.objects.select_related('stock_item', 'order', 'created_by').all()
    serializer_class = StockTransactionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['transaction_type', 'stock_item']
    search_fields = ['stock_item__name', 'stock_item__sku']
    ordering_fields = ['created_at']


# ─── Reports ─────────────────────────────────────────────────────────────────

def _parse_date(value):
    """Parses a 'YYYY-MM-DD' query param into a date, or None if absent/invalid."""
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


class ReportView(generics.GenericAPIView):
    """
    All report types accept these optional filters as query params:
      - category=<id>       (stock-based reports)
      - supplier=<id>        (stock and order-based reports)
      - start_date=YYYY-MM-DD, end_date=YYYY-MM-DD  (date-based reports)
      - export=csv           (returns a CSV download instead of JSON)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        report_type = kwargs.get('report_type')
        handlers = {
            'stock-summary': self._stock_summary,
            'reorder-alerts': self._reorder_alerts,
            'low-stock': self._low_stock,
            'order-summary': self._order_summary,
            'stock-valuation': self._stock_valuation,
            'transaction-history': self._transaction_history,
        }
        handler = handlers.get(report_type)
        if not handler:
            return Response({'error': 'Unknown report type'}, status=404)

        # Each handler returns (json_summary, csv_rows) — csv_rows is a flat
        # list of dicts (one per line item) suitable for a spreadsheet;
        # json_summary is the same shape the frontend already expects.
        summary, rows = handler(request)

        if request.query_params.get('export') == 'csv':
            return self._csv_response(rows, report_type)

        return Response(summary)

    @staticmethod
    def _csv_response(rows, report_type):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{report_type}.csv"'
        if not rows:
            response.write('No data for the selected filters\n')
            return response
        writer = csv.DictWriter(response, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        return response

    @staticmethod
    def _apply_stock_filters(request, items):
        """category=<id> and supplier=<id> filters, shared by every stock-based report."""
        category_id = request.query_params.get('category')
        supplier_id = request.query_params.get('supplier')
        if category_id:
            items = items.filter(category_id=category_id)
        if supplier_id:
            items = items.filter(supplier_id=supplier_id)
        return items

    def _stock_summary(self, request):
        items = self._apply_stock_filters(request, StockItem.objects.filter(is_active=True))
        total_items = items.count()
        total_value = sum(i.stock_value for i in items)
        low_stock_count = sum(1 for i in items if i.needs_reorder)
        out_of_stock = items.filter(quantity_in_stock=0).count()
        by_category = (
            items.values('category__name')
            .annotate(count=Count('id'), total_qty=Sum('quantity_in_stock'))
            .order_by('category__name')
        )
        summary = {
            'total_active_items': total_items,
            'total_stock_value': float(total_value),
            'low_stock_items': low_stock_count,
            'out_of_stock_items': out_of_stock,
            'by_category': list(by_category),
        }
        rows = [
            {
                'sku': i.sku, 'name': i.name,
                'category': i.category.name if i.category else '',
                'supplier': i.supplier.name if i.supplier else '',
                'quantity_in_stock': i.quantity_in_stock,
                'unit_price': str(i.unit_price),
                'stock_value': str(i.stock_value),
            }
            for i in items.select_related('category', 'supplier')
        ]
        return summary, rows

    def _reorder_alerts(self, request):
        items = self._apply_stock_filters(
            request, StockItem.objects.filter(is_active=True).select_related('supplier', 'category')
        )
        alerts = [
            {
                'id': i.id, 'sku': i.sku, 'name': i.name,
                'quantity_in_stock': i.quantity_in_stock,
                'reorder_level': i.reorder_level,
                'reorder_quantity': i.reorder_quantity,
                'supplier': i.supplier.name if i.supplier else None,
                'category': i.category.name if i.category else None,
                'shortage': max(0, i.reorder_level - i.quantity_in_stock),
            }
            for i in items if i.needs_reorder
        ]
        summary = {'count': len(alerts), 'alerts': alerts}
        return summary, alerts

    def _low_stock(self, request):
        try:
            threshold = int(request.query_params.get('threshold', 5))
        except (TypeError, ValueError):
            threshold = 5
        items = self._apply_stock_filters(
            request, StockItem.objects.filter(is_active=True, quantity_in_stock__lte=threshold)
        ).select_related('category', 'supplier')
        rows = [
            {
                'id': i.id, 'sku': i.sku, 'name': i.name,
                'category': i.category.name if i.category else '',
                'supplier': i.supplier.name if i.supplier else '',
                'quantity_in_stock': i.quantity_in_stock,
                'reorder_level': i.reorder_level,
            }
            for i in items
        ]
        summary = {'threshold': threshold, 'items': rows}
        return summary, rows

    def _order_summary(self, request):
        orders = Order.objects.all()

        supplier_id = request.query_params.get('supplier')
        if supplier_id:
            orders = orders.filter(supplier_id=supplier_id)

        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))
        if start_date:
            orders = orders.filter(created_at__date__gte=start_date)
        if end_date:
            orders = orders.filter(created_at__date__lte=end_date)

        by_status_and_type = (
            orders.values('status', 'order_type')
            .annotate(count=Count('id'))
            .order_by('order_type', 'status')
        )
        recent = orders.filter(
            created_at__gte=timezone.now() - timedelta(days=30)
        ).count()
        summary = {
            'by_status_and_type': list(by_status_and_type),
            'orders_last_30_days': recent,
            'total_orders': orders.count(),
            'filters_applied': {
                'supplier': supplier_id,
                'start_date': str(start_date) if start_date else None,
                'end_date': str(end_date) if end_date else None,
            },
        }
        rows = [
            {
                'order_number': o.order_number, 'order_type': o.order_type,
                'status': o.status, 'supplier': o.supplier.name if o.supplier else '',
                'total_amount': str(o.total_amount),
                'created_at': o.created_at.date().isoformat(),
            }
            for o in orders.select_related('supplier').prefetch_related('items')
        ]
        return summary, rows

    def _stock_valuation(self, request):
        items = self._apply_stock_filters(
            request, StockItem.objects.filter(is_active=True).select_related('category', 'supplier')
        )
        by_category = {}
        for i in items:
            cat = i.category.name if i.category else 'Uncategorised'
            by_category.setdefault(cat, {'count': 0, 'value': 0.0})
            by_category[cat]['count'] += 1
            by_category[cat]['value'] += float(i.stock_value)
        total = sum(float(i.stock_value) for i in items)
        summary = {'total_valuation': total, 'by_category': by_category}
        rows = [
            {
                'sku': i.sku, 'name': i.name,
                'category': i.category.name if i.category else '',
                'supplier': i.supplier.name if i.supplier else '',
                'quantity_in_stock': i.quantity_in_stock,
                'unit_price': str(i.unit_price),
                'stock_value': str(i.stock_value),
            }
            for i in items
        ]
        return summary, rows

    def _transaction_history(self, request):
        start_date = _parse_date(request.query_params.get('start_date'))
        end_date = _parse_date(request.query_params.get('end_date'))

        txns = StockTransaction.objects.select_related('stock_item', 'stock_item__category', 'stock_item__supplier')

        if start_date or end_date:
            # Explicit date range takes priority over the rolling "days" window.
            if start_date:
                txns = txns.filter(created_at__date__gte=start_date)
            if end_date:
                txns = txns.filter(created_at__date__lte=end_date)
            period_label = {'start_date': str(start_date) if start_date else None,
                             'end_date': str(end_date) if end_date else None}
        else:
            days = int(request.query_params.get('days', 7))
            since = timezone.now() - timedelta(days=days)
            txns = txns.filter(created_at__gte=since)
            period_label = {'period_days': days}

        category_id = request.query_params.get('category')
        supplier_id = request.query_params.get('supplier')
        if category_id:
            txns = txns.filter(stock_item__category_id=category_id)
        if supplier_id:
            txns = txns.filter(stock_item__supplier_id=supplier_id)

        by_type = txns.values('transaction_type').annotate(count=Count('id'), total_qty=Sum('quantity'))
        summary = {**period_label, 'summary': list(by_type)}
        rows = [
            {
                'stock_item': t.stock_item.name, 'sku': t.stock_item.sku,
                'transaction_type': t.transaction_type, 'quantity': t.quantity,
                'previous_quantity': t.previous_quantity, 'new_quantity': t.new_quantity,
                'notes': t.notes, 'created_at': t.created_at.isoformat(),
            }
            for t in txns.order_by('-created_at')
        ]
        return summary, rows