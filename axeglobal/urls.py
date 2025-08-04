from django.contrib import admin
from django.urls import path
from django.contrib.auth import views as auth_views
from rental import views as rental_views
from accounts import views as accounts_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', rental_views.DashboardView.as_view(), name='dashboard'),
    
    # Product URLs
    path('products/', rental_views.ProductListView.as_view(), name='product_list'),
    path('products/create/', rental_views.ProductCreateView.as_view(), name='product_create'),
    path('products/<int:pk>/', rental_views.ProductDetailView.as_view(), name='product_detail'),
    path('products/<int:pk>/update/', rental_views.ProductUpdateView.as_view(), name='product_update'),
    path('products/import/', rental_views.ProductImportView.as_view(), name='product_import'),
    path('products/<int:pk>/stock/', rental_views.ProductStockView.as_view(), name='product_stock'),
    # Customer URLs
    path('customers/', rental_views.CustomerListView.as_view(), name='customer_list'),
    path('customers/create/', rental_views.CustomerCreateView.as_view(), name='customer_create'),
    path('customers/<int:pk>/', rental_views.CustomerDetailView.as_view(), name='customer_detail'),
    path('customers/<int:pk>/update/', rental_views.CustomerUpdateView.as_view(), name='customer_update'),
    path('customers/<int:pk>/history/', rental_views.CustomerRentalHistoryView.as_view(), name='customer_history'),
    
    path('api/customers/<int:pk>/', rental_views.customer_detail_api, name='customer_api'),
    path('api/products/<int:pk>/', rental_views.product_detail_api, name='product_api'),
    # Rental URLs
    path('rentals/', rental_views.RentalListView.as_view(), name='rental_list'),
    path('rentals/create/', rental_views.CreateRentalAgreementView.as_view(), name='rental_create'),
    path('rentals/<int:pk>/', rental_views.RentalDetailView.as_view(), name='rental_detail'),
    path('rentals/<int:pk>/return/', rental_views.ReturnRentalView.as_view(), name='rental_return'),
    path('rentals/<int:pk>/invoice/', rental_views.generate_invoice_pdf, name='rental_invoice_pdf'),
    path('rentals/<int:pk>/agreement/', rental_views.generate_agreement_pdf, name='rental_agreement_pdf'),
    path('rentals/<int:rental_id>/return/', rental_views.process_rental_return, name='rental_return'),
    path('reports/monthly-revenue/', rental_views.MonthlyRevenueDetailView.as_view(), name='monthly_revenue_detail'),
    path('rental/<int:pk>/delete/', rental_views.RentalDeleteView.as_view(), name='rental_delete'),

    path('api/products/<int:pk>/price/', rental_views.get_product_price, name='product_price_api'),
    path('returns/<int:pk>/', rental_views.ReturnRentalItemView.as_view(), name='return_item'),
    path('rentals/<int:pk>/update/', rental_views.UpdateRentalAgreementView.as_view(), name='rental_update'),
    path('rentals/<int:pk>/calculate-amount/', rental_views.CalculateReturnAmountView.as_view(), name='calculate_return_amount'),
    path('invoice/<int:invoice_id>/pdf/', rental_views.invoice_pdf_view, name='invoice_pdf'),
    path('invoices/<int:pk>/', accounts_views.InvoiceDetailView.as_view(), name='invoice_detail'),
    path('reports/revenue/', rental_views.RevenueReportView.as_view(), name='revenue_report'),


    # Expense URLs
    path('expenses/', rental_views.ExpenseListView.as_view(), name='expense_list'),
    path('expenses/add/', rental_views.ExpenseCreateView.as_view(), name='expense_create'),
    path('expenses/<int:pk>/edit/', rental_views.ExpenseUpdateView.as_view(), name='expense_update'),
    path('expenses/<int:pk>/delete/', rental_views.ExpenseDeleteView.as_view(), name='expense_delete'),
    
    # Expense Category URLs
    path('expenses/categories/', rental_views.ExpenseCategoryListView.as_view(), name='expense_category_list'),
    path('expenses/categories/add/', rental_views.ExpenseCategoryCreateView.as_view(), name='expense_category_create'),
    path('expenses/categories/<int:pk>/edit/', rental_views.ExpenseCategoryUpdateView.as_view(), name='expense_category_update'),
    path('expenses/categories/<int:pk>/delete/', rental_views.ExpenseCategoryDeleteView.as_view(), name='expense_category_delete'),
    
    # Expense Report URL
    path('expenses/report/', rental_views.ExpenseReportView.as_view(), name='expense_report'),
    path('payments/create/', rental_views.PaymentCreateView.as_view(), name='payment_create'),
    # Accounting URLs
    path('financials/', accounts_views.FinancialDashboardView.as_view(), name='financial_dashboard'),
    path('financials/reports/', accounts_views.RevenueReportView.as_view(), name='revenue_report'),
    path('financials/invoices/', accounts_views.InvoiceListView.as_view(), name='invoice_list'),
    path('rentals/<int:pk>/payment/', rental_views.ProcessPaymentView.as_view(), name='process_payment'),
    
    # Authentication URLs
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='dashboard'), name='logout'),
    path('profile/', accounts_views.UserProfileView.as_view(), name='user_profile'),
    
    # Reports URLs
    path('reports/product-utilization/', rental_views.ProductUtilizationReportView.as_view(), name='product_utilization_report'),
    path('reports/customer-activity/', rental_views.CustomerActivityReportView.as_view(), name='customer_activity_report'),
    
    # Barcode URLs
    path('barcode/generate/', rental_views.generate_barcodes, name='generate_barcodes'),
    path('barcode/scan/', rental_views.BarcodeScanView.as_view(), name='barcode_scan'),
]