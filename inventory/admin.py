from django.contrib import admin
from .models import Supplier, Category, StockItem, Order, OrderItem, StockTransaction


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['name', 'contact_name', 'email', 'phone', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name', 'email']


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'description']
    search_fields = ['name']


@admin.register(StockItem)
class StockItemAdmin(admin.ModelAdmin):
    list_display = ['sku', 'name', 'category', 'supplier', 'quantity_in_stock',
                    'unit_price', 'reorder_level', 'needs_reorder', 'is_active']
    list_filter = ['category', 'supplier', 'is_active', 'unit']
    search_fields = ['sku', 'name']
    readonly_fields = ['needs_reorder', 'stock_value', 'created_at', 'updated_at']


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_number', 'order_type', 'supplier', 'status', 'total_amount', 'created_at']
    list_filter = ['status', 'order_type']
    search_fields = ['order_number']
    readonly_fields = ['order_number', 'total_amount', 'created_at']
    inlines = [OrderItemInline]


@admin.register(StockTransaction)
class StockTransactionAdmin(admin.ModelAdmin):
    list_display = ['stock_item', 'transaction_type', 'quantity', 'previous_quantity',
                    'new_quantity', 'created_by', 'created_at']
    list_filter = ['transaction_type']
    readonly_fields = ['created_at']
