from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from inventory.models import Supplier, Category, StockItem


class Command(BaseCommand):
    help = 'Seed the database with sample data'

    def handle(self, *args, **kwargs):
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser('admin', 'admin@example.com', 'admin1234')
            self.stdout.write(self.style.SUCCESS('Created superuser: admin / admin1234'))

        cats = ['Electronics', 'Office Supplies', 'Furniture', 'Cleaning', 'Safety']
        cat_objs = {name: Category.objects.get_or_create(name=name)[0] for name in cats}

        suppliers_data = [
            {'name': 'TechCorp Ltd', 'email': 'orders@techcorp.com', 'phone': '+1-555-0101'},
            {'name': 'OfficeWorld', 'email': 'supply@officeworld.com', 'phone': '+1-555-0102'},
            {'name': 'SafeGuard Inc', 'email': 'info@safeguard.com', 'phone': '+1-555-0103'},
        ]
        sup_objs = []
        for s in suppliers_data:
            obj, _ = Supplier.objects.get_or_create(name=s['name'], defaults=s)
            sup_objs.append(obj)

        items = [
            {'sku': 'ELEC-001', 'name': 'Laptop 15"', 'category': cat_objs['Electronics'], 'supplier': sup_objs[0], 'unit_price': 899.99, 'quantity_in_stock': 25, 'reorder_level': 5},
            {'sku': 'ELEC-002', 'name': 'Wireless Mouse', 'category': cat_objs['Electronics'], 'supplier': sup_objs[0], 'unit_price': 29.99, 'quantity_in_stock': 3, 'reorder_level': 10},
            {'sku': 'OFF-001', 'name': 'A4 Paper (Ream)', 'category': cat_objs['Office Supplies'], 'supplier': sup_objs[1], 'unit_price': 4.99, 'quantity_in_stock': 200, 'reorder_level': 50},
            {'sku': 'OFF-002', 'name': 'Ballpoint Pens (Box)', 'category': cat_objs['Office Supplies'], 'supplier': sup_objs[1], 'unit_price': 6.99, 'quantity_in_stock': 8, 'reorder_level': 20},
            {'sku': 'SAF-001', 'name': 'Hard Hat', 'category': cat_objs['Safety'], 'supplier': sup_objs[2], 'unit_price': 22.50, 'quantity_in_stock': 0, 'reorder_level': 15},
        ]
        for i in items:
            StockItem.objects.get_or_create(sku=i['sku'], defaults=i)

        self.stdout.write(self.style.SUCCESS('Seed data loaded successfully!'))
