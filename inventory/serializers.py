from decimal import Decimal, InvalidOperation

from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer

from .models import Supplier, Category, StockItem, Order, OrderItem, StockTransaction


# ─── Auth tokens ─────────────────────────────────────────────────────────────

class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Same login flow as the default TokenObtainPairSerializer, but the
    response also includes basic user/role info so the frontend doesn't
    need a second request just to find out if the user is staff.
    """

    def validate(self, attrs):
        data = super().validate(attrs)
        data['user'] = {
            'id': self.user.id,
            'username': self.user.username,
            'email': self.user.email,
            'is_staff': self.user.is_staff,
        }
        return data

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['is_staff'] = user.is_staff
        return token


# ─── Users ───────────────────────────────────────────────────────────────────

class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False, validators=[validate_password])

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'password', 'is_staff']
        read_only_fields = ['id', 'is_staff']

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        if not password:
            raise serializers.ValidationError({'password': 'This field is required when creating a user.'})
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


# ─── Suppliers ───────────────────────────────────────────────────────────────

class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = '__all__'

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Supplier name cannot be blank.")
        qs = Supplier.objects.filter(name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A supplier with this name already exists.")
        return value

    def validate_email(self, value):
        if value:
            qs = Supplier.objects.filter(email__iexact=value)
            if self.instance:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise serializers.ValidationError("A supplier with this email already exists.")
        return value

    def validate_phone(self, value):
        if value and not value.replace('+', '').replace(' ', '').replace('-', '').isdigit():
            raise serializers.ValidationError("Enter a valid phone number.")
        return value


# ─── Categories ──────────────────────────────────────────────────────────────

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Category name cannot be blank.")
        qs = Category.objects.filter(name__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError("A category with this name already exists.")
        return value


# ─── Stock Items ─────────────────────────────────────────────────────────────

class StockItemSerializer(serializers.ModelSerializer):
    needs_reorder = serializers.BooleanField(read_only=True)
    stock_value = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = StockItem
        fields = [
            'id', 'sku', 'name', 'description', 'category', 'supplier',
            'unit', 'unit_price', 'quantity_in_stock', 'reorder_level',
            'reorder_quantity', 'is_active', 'needs_reorder', 'stock_value',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
        extra_kwargs = {
            'sku': {'required': True, 'allow_blank': False},
            'name': {'required': True, 'allow_blank': False},
            'unit_price': {'required': True},
            'quantity_in_stock': {'required': True},
        }

    # ── field-level validation ──

    def validate_sku(self, value):
        value = value.strip().upper()
        if not value:
            raise serializers.ValidationError("SKU cannot be blank.")
        qs = StockItem.objects.filter(sku__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError(f"A stock item with SKU '{value}' already exists.")
        return value

    def validate_name(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Name cannot be blank.")
        return value

    def validate_unit_price(self, value):
        try:
            value = Decimal(value)
        except (InvalidOperation, TypeError):
            raise serializers.ValidationError("Unit price must be a valid number.")
        if value <= Decimal('0.00'):
            raise serializers.ValidationError("Unit price must be greater than zero.")
        if value.as_tuple().exponent < -2:
            raise serializers.ValidationError("Unit price cannot have more than 2 decimal places.")
        return value

    def validate_quantity_in_stock(self, value):
        if value < 0:
            raise serializers.ValidationError("Quantity in stock cannot be negative.")
        return value

    def validate_reorder_level(self, value):
        if value < 0:
            raise serializers.ValidationError("Reorder level cannot be negative.")
        return value

    def validate_reorder_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("Reorder quantity must be greater than zero.")
        return value

    # ── object-level validation ──

    def validate(self, data):
        reorder_level = data.get(
            'reorder_level', self.instance.reorder_level if self.instance else None
        )
        reorder_quantity = data.get(
            'reorder_quantity', self.instance.reorder_quantity if self.instance else None
        )
        if reorder_level is not None and reorder_quantity is not None:
            if reorder_quantity < reorder_level:
                raise serializers.ValidationError({
                    'reorder_quantity': 'Reorder quantity should be greater than or equal to the reorder level.'
                })
        return data


class StockItemListSerializer(serializers.ModelSerializer):
    needs_reorder = serializers.BooleanField(read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True, default=None)

    class Meta:
        model = StockItem
        fields = [
            'id', 'sku', 'name', 'category_name', 'supplier_name', 'unit',
            'unit_price', 'quantity_in_stock', 'reorder_level',
            'needs_reorder', 'is_active',
        ]


class StockAdjustmentSerializer(serializers.Serializer):
    quantity = serializers.IntegerField(required=True)
    notes = serializers.CharField(required=False, allow_blank=True, max_length=500)

    def validate_quantity(self, value):
        if value == 0:
            raise serializers.ValidationError("Adjustment quantity cannot be zero.")
        return value


# ─── Orders ──────────────────────────────────────────────────────────────────

class OrderItemSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='stock_item.name', read_only=True)
    sku = serializers.CharField(source='stock_item.sku', read_only=True)
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ['id', 'stock_item', 'item_name', 'sku', 'quantity', 'unit_price', 'subtotal']
        extra_kwargs = {
            'stock_item': {'required': True},
            'quantity': {'required': True},
            'unit_price': {'required': True},
        }

    def validate_stock_item(self, value):
        if not value.is_active:
            raise serializers.ValidationError(f"Stock item '{value.name}' is inactive and cannot be ordered.")
        return value

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("Quantity must be greater than zero.")
        return value

    def validate_unit_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Unit price cannot be negative.")
        return value


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True)
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    created_by = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'order_type', 'supplier', 'status', 'notes',
            'created_by', 'created_at', 'updated_at', 'expected_delivery',
            'items', 'total_amount',
        ]
        # status is read-only here on purpose: every status change must go through
        # OrderViewSet.update_status, which enforces the valid transition graph and
        # locks stock rows before anything moves. Allowing status here would let a
        # plain PATCH jump straight to "received" and skip all of that.
        read_only_fields = ['id', 'order_number', 'status', 'created_by', 'created_at', 'updated_at']

    def validate_items(self, value):
        if not value:
            raise serializers.ValidationError("An order must contain at least one item.")
        seen = set()
        for item in value:
            stock_item = item.get('stock_item')
            if stock_item and stock_item.pk in seen:
                raise serializers.ValidationError(
                    f"Duplicate stock item '{stock_item.name}' in order items; combine quantities instead."
                )
            if stock_item:
                seen.add(stock_item.pk)
        return value

    def validate(self, data):
        order_type = data.get('order_type', self.instance.order_type if self.instance else 'purchase')
        supplier = data.get('supplier', self.instance.supplier if self.instance else None)
        if order_type == 'purchase' and supplier is None:
            raise serializers.ValidationError({'supplier': 'A supplier is required for purchase orders.'})

        # Once an order has moved past 'pending', its items/type/supplier are locked.
        # Editing them later would silently disconnect the order from whatever stock
        # movement already happened (or is about to) for the original line items.
        if self.instance and self.instance.status != 'pending':
            locked_fields = [f for f in ('items', 'order_type', 'supplier') if f in data]
            if locked_fields:
                raise serializers.ValidationError(
                    f"Cannot change {', '.join(locked_fields)} on an order that is no longer pending "
                    f"(current status: '{self.instance.status}'). Cancel and recreate the order instead."
                )
        return data

    def create(self, validated_data):
        items_data = validated_data.pop('items')
        order = Order.objects.create(**validated_data)
        for item_data in items_data:
            OrderItem.objects.create(order=order, **item_data)
        return order

    def update(self, instance, validated_data):
        items_data = validated_data.pop('items', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        if items_data is not None:
            instance.items.all().delete()
            for item_data in items_data:
                OrderItem.objects.create(order=instance, **item_data)
        return instance


class OrderListSerializer(serializers.ModelSerializer):
    supplier_name = serializers.CharField(source='supplier.name', read_only=True, default=None)
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=2, read_only=True)
    item_count = serializers.IntegerField(source='items.count', read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'order_number', 'order_type', 'supplier_name', 'status',
            'created_at', 'expected_delivery', 'total_amount', 'item_count',
        ]


# ─── Stock Transactions ────────────────────────────────────────────────────────

class StockTransactionSerializer(serializers.ModelSerializer):
    stock_item_name = serializers.CharField(source='stock_item.name', read_only=True)
    sku = serializers.CharField(source='stock_item.sku', read_only=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, default=None)

    class Meta:
        model = StockTransaction
        fields = [
            'id', 'stock_item', 'stock_item_name', 'sku', 'transaction_type',
            'quantity', 'previous_quantity', 'new_quantity', 'order', 'notes',
            'created_by', 'created_by_username', 'created_at',
        ]
        read_only_fields = ['id', 'previous_quantity', 'new_quantity', 'created_by', 'created_at']