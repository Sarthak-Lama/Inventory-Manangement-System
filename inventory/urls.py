from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

router = DefaultRouter()
router.register(r'suppliers', views.SupplierViewSet)
router.register(r'categories', views.CategoryViewSet)
router.register(r'stock-items', views.StockItemViewSet)
router.register(r'orders', views.OrderViewSet)
router.register(r'transactions', views.StockTransactionViewSet)

urlpatterns = [
    path('', include(router.urls)),
    path('auth/register/', views.RegisterView.as_view(), name='register'),
    path('auth/profile/', views.ProfileView.as_view(), name='profile'),
    path('auth/logout/', views.LogoutView.as_view(), name='logout'),
    path('reports/<str:report_type>/', views.ReportView.as_view(), name='reports'),
]