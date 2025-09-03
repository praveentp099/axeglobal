from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView, TemplateView, FormView
from django.urls import reverse_lazy
from datetime import date
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum, Count, Q, F
from django.utils import timezone
from django.http import HttpResponse, JsonResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from io import BytesIO
from decimal import Decimal
from django.db.models.functions import Coalesce
from django.db.models import DecimalField
from django.contrib.auth.mixins import LoginRequiredMixin
from dateutil.relativedelta import relativedelta
from django.views.decorators.http import require_GET
from barcode.writer import ImageWriter
from django.core.files import File
from django.core.exceptions import ValidationError
import barcode
from barcode.writer import ImageWriter
from .models import (
    Product, Customer, RentalAgreement, RentalItem, 
    Payment, Invoice, Expense, ExpenseCategory, RevenueReport
)
from .forms import (
    ProductForm, CustomerForm, RentalAgreementForm, 
    RentalItemForm, RentalItemFormSet, PaymentForm,
    ExpenseForm, ExpenseCategoryForm, ProductImportForm, ProductStockForm
)
from .forms import ReturnRentalForm 
from django.utils.crypto import get_random_string
from datetime import timedelta, datetime

class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = 'rental/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.localdate()
        current_year = today.year
        current_month = today.month
        last_month = today - relativedelta(months=1)
        last_month_year = last_month.year
        last_month_month = last_month.month

        # Basic stats (unchanged)
        context['total_products'] = Product.objects.count()
        context['total_customers'] = Customer.objects.count()

        # Product investment (unchanged)
        owned_products = Product.objects.filter(
            is_outsourced=False,
            purchase_price__isnull=False,
            stock__gt=0
        )
        context['product_investment'] = owned_products.aggregate(
            total_investment=Sum('purchase_price')
        )['total_investment'] or 0 # Example

        # NEW PAYMENT-BASED REVENUE CALCULATION
        def get_payment_revenue(year, month):
            return Payment.objects.filter(
                payment_date__year=year,
                payment_date__month=month
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        current_month_revenue = get_payment_revenue(current_year, current_month)
        last_month_revenue = get_payment_revenue(last_month_year, last_month_month)
        
        # Revenue change calculation (unchanged logic)
        context['monthly_revenue'] = current_month_revenue
        context['revenue_change'] = self._calculate_percentage_change(last_month_revenue, current_month_revenue)

        # Expenses (unchanged)
        def get_expenses(year, month):
            return Expense.objects.filter(
                date__year=year,
                date__month=month
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')

        current_month_expenses = get_expenses(current_year, current_month)
        last_month_expenses = get_expenses(last_month_year, last_month_month)
        
        context['monthly_expenses'] = current_month_expenses
        context['expense_change'] = self._calculate_percentage_change(last_month_expenses, current_month_expenses)

        # Net profit (unchanged logic)
        net_profit = current_month_revenue - current_month_expenses
        last_month_profit = (last_month_revenue - last_month_expenses) if last_month_revenue else Decimal('0.00')
        context['net_profit'] = net_profit
        context['profit_change'] = self._calculate_percentage_change(last_month_profit, net_profit)

        # Rental stats (unchanged)
        context.update(self._get_rental_stats(today, last_month))
        
        # Recent activity (unchanged)
        context['recent_rentals'] = RentalAgreement.objects.select_related('customer').order_by('-created_at')[:5]
        context['recent_expenses'] = Expense.objects.select_related('category').order_by('-date')[:5]

        # Customer growth (unchanged)
        context['customer_growth'] = self._calculate_customer_growth(today, last_month)

        # Chart Data (now uses Payment model)
        context.update(self._get_chart_data(today))
        
        return context

    # Helper Methods
    def _calculate_percentage_change(self, old, new):
        if not old or old == 0:
            return 100 if new > 0 else 0
        return round(((new - old) / old) * 100, 1)

    def _get_rental_stats(self, today, last_month):
        stats = {}
        
        # Active rentals
        stats['active_rentals'] = RentalAgreement.objects.filter(status='active').count()
        last_month_active = RentalAgreement.objects.filter(
            status='active',
            start_date__lte=last_month,
            expected_return_date__gte=last_month
        ).count()
        stats['active_rentals_change'] = self._calculate_percentage_change(last_month_active, stats['active_rentals'])

        # Overdue rentals
        overdue = RentalAgreement.objects.filter(
            status='active',
            expected_return_date__lt=today
        ).annotate(days_overdue=today - F('expected_return_date'))
        stats['overdue_rentals'] = overdue.count()
        stats['overdue_rentals_list'] = overdue.order_by('expected_return_date')[:5]
        
        last_month_overdue = RentalAgreement.objects.filter(
            status='active',
            expected_return_date__lt=last_month
        ).count()
        stats['overdue_rentals_change'] = self._calculate_percentage_change(last_month_overdue, stats['overdue_rentals'])
        
        return stats

    def _calculate_customer_growth(self, today, last_month):
        current = Customer.objects.count()
        last_month_count = Customer.objects.filter(join_date__lte=last_month).count()
        return self._calculate_percentage_change(last_month_count, current)

    def _get_chart_data(self, today):
        # Revenue chart (now payment-based)
        revenue_data, revenue_labels = [], []
        for i in range(5, -1, -1):  # Last 6 months
            month = today - relativedelta(months=i)
            revenue = Payment.objects.filter(
                payment_date__year=month.year,
                payment_date__month=month.month
            ).aggregate(total=Sum('amount'))['total'] or 0
            revenue_data.append(float(revenue))
            revenue_labels.append(month.strftime('%b %Y'))
        
        # Status chart (unchanged)
        status_data = RentalAgreement.objects.aggregate(
            active=Count('id', filter=Q(status='active')),
            returned=Count('id', filter=Q(status='returned')),
            overdue=Count('id', filter=Q(status='overdue')),
            cancelled=Count('id', filter=Q(status='cancelled'))
        )
        
        return {
            'revenue_data': revenue_data,
            'revenue_labels': revenue_labels,
            'status_data': [status_data[k] for k in ['active', 'returned', 'overdue', 'cancelled']]
        }

# Expense Views
class ExpenseCategoryListView(LoginRequiredMixin, ListView):
    model = ExpenseCategory
    template_name = 'expenses/expense_category_list.html'
    context_object_name = 'categories'

class ExpenseCategoryCreateView(LoginRequiredMixin, CreateView):
    model = ExpenseCategory
    form_class = ExpenseCategoryForm
    template_name = 'expenses/expense_category_form.html'
    success_url = reverse_lazy('expense_category_list')

class ExpenseCategoryUpdateView(LoginRequiredMixin, UpdateView):
    model = ExpenseCategory
    form_class = ExpenseCategoryForm
    template_name = 'expenses/expense_category_form.html'
    success_url = reverse_lazy('expense_category_list')

class ExpenseCategoryDeleteView(LoginRequiredMixin, DeleteView):
    model = ExpenseCategory
    template_name = 'expenses/expense_category_confirm_delete.html'
    success_url = reverse_lazy('expense_category_list')

class ExpenseListView(LoginRequiredMixin, ListView):
    model = Expense
    template_name = 'expenses/expense_list.html'
    context_object_name = 'expenses'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset()
        
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        if start_date and end_date:
            queryset = queryset.filter(date__range=[start_date, end_date])
        
        category = self.request.GET.get('category')
        if category:
            queryset = queryset.filter(category_id=category)
        
        product = self.request.GET.get('product')
        if product:
            queryset = queryset.filter(product_id=product)
        
        return queryset.order_by('-date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categories'] = ExpenseCategory.objects.all()
        context['products'] = Product.objects.filter(is_outsourced=True)
        context['total'] = self.get_queryset().aggregate(total=Sum('amount'))['total'] or 0
        return context

class ExpenseCreateView(LoginRequiredMixin, CreateView):
    model = Expense
    form_class = ExpenseForm
    template_name = 'expenses/expense_form.html'
    success_url = reverse_lazy('expense_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Expense recorded successfully!')
        return response

class ExpenseUpdateView(LoginRequiredMixin, UpdateView):
    model = Expense
    form_class = ExpenseForm
    template_name = 'expenses/expense_form.html'
    success_url = reverse_lazy('expense_list')

class ExpenseDeleteView(LoginRequiredMixin, DeleteView):
    model = Expense
    template_name = 'expenses/expense_confirm_delete.html'
    success_url = reverse_lazy('expense_list')

class ExpenseReportView(LoginRequiredMixin, TemplateView):
    template_name = 'expenses/expense_report.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        
        expenses = Expense.objects.all()
        if start_date and end_date:
            expenses = expenses.filter(date__range=[start_date, end_date])
        
        by_category = expenses.values('category__name').annotate(
            total=Sum('amount')
        ).order_by('-total')
        
        total = expenses.aggregate(total=Sum('amount'))['total'] or 0
        
        # Calculate percentages
        for item in by_category:
            item['percentage'] = (item['total'] / total) * 100 if total else 0
        
        context['expenses'] = expenses.order_by('-date')
        context['by_category'] = by_category
        context['total'] = total
        return context
    
class PaymentCreateView(LoginRequiredMixin, CreateView):
    model = Payment
    form_class = PaymentForm
    template_name = 'rental/payment_form.html'
    success_url = reverse_lazy('invoice_list')

    def get_initial(self):
        initial = super().get_initial()
        if 'invoice_id' in self.request.GET:
            try:
                invoice = Invoice.objects.get(pk=self.request.GET.get('invoice_id'))
                initial.update({
                    'rental_agreement': invoice.rental_agreement,
                    'amount': invoice.balance_due
                })
            except Invoice.DoesNotExist:
                pass
        return initial

    def form_valid(self, form):
        payment = form.save(commit=False)
        payment.processed_by = self.request.user
        payment.save()
        messages.success(self.request, 'Payment recorded successfully!')
        return super().form_valid(form)

# Product Views
class ProductListView(LoginRequiredMixin, ListView):
    model = Product
    ordering = ['-created_at'] 
    template_name = 'rental/product_list.html'
    context_object_name = 'products'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.GET.get('q')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | 
                Q(sku__icontains=search) |
                Q(description__icontains=search))
        return queryset

class ProductCreateView(LoginRequiredMixin, CreateView):
    model = Product
    form_class = ProductForm
    template_name = 'rental/product_form.html'
    success_url = reverse_lazy('product_list')

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, 'Product created successfully!')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)

class ProductUpdateView(LoginRequiredMixin, UpdateView):
    model = Product
    form_class = ProductForm
    template_name = 'rental/product_form.html'
    success_url = reverse_lazy('product_list')

    def form_valid(self, form):
        messages.success(self.request, 'Product updated successfully!')
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(self.request, 'Please correct the errors below.')
        return super().form_invalid(form)

class ProductDetailView(LoginRequiredMixin, DetailView):
    model = Product
    template_name = 'rental/product_detail.html'
    context_object_name = 'product'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['expenses'] = self.object.expenses.order_by('-date')
        context['rental_history'] = self.object.rental_items.order_by('-agreement__start_date')
        context['total_expenses'] = self.object.total_expenses
        context['net_revenue'] = self.object.net_revenue
        return context


class ProductImportView(LoginRequiredMixin, FormView):
    template_name = 'rental/product_import.html'
    form_class = ProductImportForm
    success_url = reverse_lazy('product_list')

    def form_valid(self, form):
        created_count, errors = form.process_import()
        if errors:
            for error_msg in errors:
                messages.error(self.request, error_msg)
            messages.warning(self.request, f"Import completed with {created_count} products created but some errors occurred.")
            return self.form_invalid(form)
        else:
            messages.success(self.request, f"{created_count} products imported successfully!")
            return super().form_valid(form)

class ProductStockView(LoginRequiredMixin, UpdateView):
    model = Product
    form_class = ProductStockForm
    template_name = 'rental/product_stock.html'
    success_url = reverse_lazy('product_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Stock for {self.object.name} updated to {self.object.stock}.')
        return response

# Customer Views
class CustomerListView(ListView):
    model = Customer
    template_name = 'rental/customer_list.html'
    context_object_name = 'customers'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset()
        search_query = self.request.GET.get('search', '').strip()
        
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(email__icontains=search_query) |
                Q(phone__icontains=search_query) |
                Q(company__icontains=search_query)
            )
        return queryset.order_by('name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('search', '')
        return context

class CustomerCreateView(LoginRequiredMixin, CreateView):
    model = Customer
    form_class = CustomerForm
    template_name = 'rental/customer_form.html'
    success_url = reverse_lazy('customer_list')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, 'Customer created successfully!')
        return response

class CustomerDetailView(LoginRequiredMixin, DetailView):
    model = Customer
    template_name = 'rental/customer_detail.html'
    context_object_name = 'customer'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rentals = RentalAgreement.objects.filter(customer=self.object)
        context['total_spent'] = rentals.aggregate(total=Sum('invoice__total_amount'))['total'] or 0
        context['completed_rentals'] = rentals.filter(status='returned').count()
        context['active_rentals'] = rentals.filter(status='active').count()
        context['overdue_rentals'] = rentals.filter(
            status='active',
            expected_return_date__lt=timezone.now().date()
        ).count()
        context['recent_activity'] = rentals.order_by('-start_date')[:5]
        return context

class CustomerUpdateView(LoginRequiredMixin, UpdateView):
    model = Customer
    form_class = CustomerForm
    template_name = 'rental/customer_form.html'
    success_url = reverse_lazy('customer_list')

class CustomerRentalHistoryView(LoginRequiredMixin, ListView):
    model = RentalAgreement
    template_name = 'rental/customer_rental_history.html'
    context_object_name = 'rentals'
    paginate_by = 10

    def get_queryset(self):
        customer = get_object_or_404(Customer, pk=self.kwargs['pk'])
        return super().get_queryset().filter(customer=customer).order_by('-start_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customer = get_object_or_404(Customer, pk=self.kwargs['pk'])
        context['customer'] = customer
        rentals = self.get_queryset()
        context['total_spent'] = rentals.aggregate(total=Sum('invoice__total_amount'))['total'] or 0
        context['completed_rentals'] = rentals.filter(status='returned').count()
        context['active_rentals'] = rentals.filter(status='active').count()
        context['overdue_rentals'] = rentals.filter(
            status='active',
            expected_return_date__lt=timezone.now().date()
        ).count()
        context['recent_activity'] = rentals.order_by('-start_date')[:5]
        return context

# Rental Agreement Views
class RentalListView(LoginRequiredMixin, ListView):
    model = RentalAgreement
    template_name = 'rental/rental_list.html'
    context_object_name = 'rentals'
    paginate_by = 20
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = super().get_queryset()
        status_filter = self.request.GET.get('status')
        customer_search = self.request.GET.get('customer')

        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if customer_search:
            queryset = queryset.filter(customer__name__icontains=customer_search)
        
        return queryset

class CreateRentalAgreementView(CreateView):
    model = RentalAgreement
    form_class = RentalAgreementForm
    template_name = 'rental/create_rental.html'
    success_url = reverse_lazy('rental_list')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['items'] = RentalItemFormSet(
                self.request.POST,
                prefix='items'
            )
        else:
            context['items'] = RentalItemFormSet(
                queryset=RentalItem.objects.none(),
                prefix='items'
            )
        return context

    def form_valid(self, form):
        context = self.get_context_data()
        items_formset = context['items']

        if not form.is_valid():
            return self.form_invalid(form)

        if not items_formset.is_valid():
            messages.error(self.request, "Please correct errors in rental items.")
            return self.form_invalid(form)

        # Check for at least one valid item
        has_valid_items = any(
            item_form.cleaned_data and
            not item_form.cleaned_data.get('DELETE', False) and
            item_form.cleaned_data.get('product')
            for item_form in items_formset
        )

        if not has_valid_items:
            form.add_error(None, "Please add at least one product to the rental agreement.")
            return self.form_invalid(form)

        try:
            with transaction.atomic():
                self.object = form.save(commit=False)
                self.object.created_by = self.request.user

                # Apply customer discount if available
                if self.object.customer.discount_rate:
                    self.object.discount = self.object.customer.discount_rate

                self.object.save()  # Save parent first to get ID

                # Save rental items - use correct FK field name (likely 'rental')
                for item_form in items_formset:
                    if (item_form.cleaned_data and
                        not item_form.cleaned_data.get('DELETE', False) and
                        item_form.cleaned_data.get('product')):
                        item = item_form.save(commit=False)
                        item.rental = self.object  # <-- Here is the fix (use correct FK field)
                        item.save()

                # Update totals and save rental agreement again if needed
                self.object.update_totals()

                # Create invoice
                Invoice.objects.create(
                    rental_agreement=self.object,
                    invoice_number=f"INV-{self.object.id:05d}",
                    due_date=self.object.expected_return_date,
                    total_amount=self.object.total
                )

                messages.success(self.request, 'Rental agreement created successfully!')
                return redirect(self.get_success_url())

        except ValidationError as e:
            messages.error(self.request, str(e))
            return self.form_invalid(form)
        except Exception as e:
            messages.error(self.request, f"An error occurred: {str(e)}")
            return self.form_invalid(form)

    def form_invalid(self, form):
        messages.error(self.request, "Please correct the errors below.")
        return super().form_invalid(form)

class UpdateRentalAgreementView(LoginRequiredMixin, UpdateView):
    model = RentalAgreement
    form_class = RentalAgreementForm
    template_name = 'rental/update_rental.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.request.POST:
            context['items'] = RentalItemFormSet(self.request.POST, instance=self.object, prefix='items')
            context['payment_form'] = PaymentForm(self.request.POST)
        else:
            context['items'] = RentalItemFormSet(instance=self.object, prefix='items')
            context['payment_form'] = PaymentForm(initial={'amount': self.object.balance_due})
        return context
    
    def form_valid(self, form):
        context = self.get_context_data()
        items_formset = context['items']
        payment_form = context['payment_form']
        
        if not items_formset.is_valid():
            messages.error(self.request, "Please correct errors in rental items.")
            return self.form_invalid(form)
            
        payment_submitted = payment_form.is_valid() and payment_form.cleaned_data.get('amount', 0) > 0

        try:
            with transaction.atomic():
                self.object = form.save()
                
                items_formset.instance = self.object
                items_formset.save()
                
                if payment_submitted:
                    payment = payment_form.save(commit=False)
                    payment.rental_agreement = self.object
                    payment.save()
                    messages.success(self.request, f'Payment of ${payment.amount:.2f} processed successfully!')

                self.object.update_totals()
                self.object.save()

                messages.success(self.request, 'Rental agreement updated successfully!')
                return redirect('rental_detail', pk=self.object.pk)
                
        except Exception as e:
            messages.error(self.request, f"An error occurred: {str(e)}")
            return self.form_invalid(form)

class RentalDetailView(LoginRequiredMixin, DetailView):
    model = RentalAgreement
    template_name = 'rental/rental_detail.html'
    context_object_name = 'rental'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['payments'] = self.object.payments.all().order_by('-payment_date')
        context['invoice'] = getattr(self.object, 'invoice', None)
        return context
    
from django.views import View



import logging

logger = logging.getLogger(__name__)


class ReturnRentalView(LoginRequiredMixin, View):
    template_name = 'rental/return_rental.html'

    def get_rental(self, pk):
        return get_object_or_404(RentalAgreement, pk=pk)

    def get_form(self, request, rental):
        form_class = ReturnRentalForm
        if request.method == 'POST':
            form = form_class(request.POST, rental=rental)  # pass rental here
        else:
            amount_to_collect = max(
                Decimal('0.00'),
                sum(
                    item.rental_price * item.quantity * rental.rental_days
                    for item in rental.items.all()
                ) - rental.advance_payment
            )
            form = form_class(
                initial={
                    'return_date': timezone.now().date(),
                    'amount_to_collect': amount_to_collect,
                }, 
                rental=rental  # pass rental here as well
            )
        return form

    def get_context_data(self, rental, form=None, posted_data=None):
        today = timezone.now().date()

        original_total = sum(
            item.rental_price * item.quantity * rental.rental_days
            for item in rental.items.all()
        )
        original_daily_rate = original_total / rental.rental_days if rental.rental_days > 0 else Decimal('0.00')

        rental_days = (today - rental.start_date).days + 1
        base_amount = original_daily_rate * rental_days
        discount_amount = base_amount * (rental.discount / Decimal('100'))
        subtotal = base_amount - discount_amount
        vat_amount = subtotal * Decimal('0.05') if rental.apply_vat else Decimal('0.00')
        actual_total = subtotal + vat_amount
        balance_due = max(Decimal('0.00'), actual_total - rental.advance_payment)

        if not form:
            form = self.get_form(self.request, rental)

        return {
            'rental': rental,
            'form': form,
            'today': today,
            'overdue_days': max(0, (today - rental.expected_return_date).days),
            'rental_days': rental_days,
            'daily_rate': original_daily_rate,
            'base_amount': base_amount,
            'discount_amount': discount_amount,
            'vat_amount': vat_amount,
            'actual_total': actual_total,
            'balance_due': balance_due,
            'original_rental_days': rental.rental_days,
            'original_total': original_total,
            'advance_payment': rental.advance_payment,
            'items': rental.items.all(),
            'posted_data': posted_data or {},
        }

    def get(self, request, pk):
        rental = self.get_rental(pk)
        if rental.status != 'active':
            messages.warning(request, f"Rental #{rental.id} is already {rental.get_status_display().lower()}.")
            return redirect('rental_detail', pk=rental.pk)

        context = self.get_context_data(rental)
        return render(request, self.template_name, context)

    def process_return(self, rental, cleaned_data):
        return_date = cleaned_data.get('return_date')
        if not return_date:
            raise ValueError("Return date is missing.")
        amount_collected = cleaned_data.get('amount_to_collect') or Decimal('0.00')
        payment_method = cleaned_data.get('payment_method')
        notes = cleaned_data.get('notes')

        # Update rental
        rental.return_date = return_date
        rental.is_returned = True
        rental.status = 'returned'  # adjust as per your model's choices
        rental.save()

        # Calculate actual total for invoice update
        original_total = sum(
            item.rental_price * item.quantity * rental.rental_days
            for item in rental.items.all()
        )
        original_daily_rate = original_total / rental.rental_days if rental.rental_days > 0 else Decimal('0.00')
        rental_days = (return_date - rental.start_date).days + 1
        base_amount = original_daily_rate * rental_days
        discount_amount = base_amount * (rental.discount / Decimal('100'))
        subtotal = base_amount - discount_amount
        vat_amount = subtotal * Decimal('0.05') if rental.apply_vat else Decimal('0.00')
        actual_total = subtotal + vat_amount

        # Update invoice
        self.update_invoice(rental, return_date, actual_total, amount_collected)

        # Create Payment record for amount collected at return
        payment = Payment.objects.create(
            rental_agreement=rental,
            amount=amount_collected,
            payment_date=return_date,
            payment_method=payment_method,
            notes=notes
        )

        # Generate and save receipt_number (requires 'receipt_number' field on Payment model)
        receipt_num = f"RCPT-{payment.id:06d}"
        payment.receipt_number = receipt_num
        payment.save()

        # Update product stocks
        self.update_product_stocks(rental.items.all())

    def update_invoice(self, rental, return_date, actual_total, amount_collected):
        invoice, created = Invoice.objects.get_or_create(
            rental_agreement=rental,
            defaults={
                'invoice_number': f"INV-{rental.id:05d}-RET",
                'issue_date': return_date,
                'due_date': return_date,
                'total_amount': actual_total,
                'paid_amount': amount_collected,
                'payment_status': 'paid' if amount_collected >= actual_total else 'partial'
            }
        )
        if not created:
            Invoice.objects.filter(pk=invoice.pk).update(
                issue_date=return_date,
                due_date=return_date,
                total_amount=actual_total,
                paid_amount=F('paid_amount') + amount_collected,
            )
            invoice.refresh_from_db()
            invoice.update_payment_status()
            invoice.save()

    def update_product_stocks(self, items):
        for item in items:
            if not item.product.is_outsourced:
                item.product.stock = F('stock') + item.quantity
                item.product.save()

    def post(self, request, pk):
        rental = self.get_rental(pk)
        if rental.status != 'active':
            messages.warning(request, f"Rental #{rental.id} is already {rental.get_status_display().lower()}.")
            return redirect('rental_detail', pk=rental.pk)

        form = self.get_form(request, rental)

        if form.is_valid():
            try:
                self.process_return(rental, form.cleaned_data)
                messages.success(request, "Rental return processed successfully.")
                return redirect('rental_detail', pk=rental.pk)
            except Exception as e:
                logger.error(f"Error processing return: {str(e)}", exc_info=True)
                messages.error(request, f"An error occurred while processing the return: {str(e)}")
                context = self.get_context_data(rental, form=form, posted_data=request.POST)
                return render(request, self.template_name, context)

        # Form invalid, show errors
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{field}: {error}")

        context = self.get_context_data(rental, form=form, posted_data=request.POST)
        return render(request, self.template_name, context)
    
def process_rental_return(request, rental_id):
    rental = get_object_or_404(RentalAgreement, id=rental_id)
    
    if request.method == 'POST':
        form = ReturnRentalForm(request.POST, rental=rental)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Update rental details
                    return_date = form.cleaned_data['return_date']
                    rental.actual_return_date = return_date
                    
                    # Calculate actual rental days
                    actual_rental_days = (return_date - rental.start_date).days + 1
                    
                    # Calculate new totals based on actual days
                    daily_rate = rental.subtotal / rental.rental_days if rental.rental_days > 0 else 0
                    base_amount = daily_rate * actual_rental_days
                    discount_amount = base_amount * (rental.discount / 100)
                    subtotal = base_amount - discount_amount
                    vat_amount = subtotal * 0.05 if rental.apply_vat else 0
                    total = subtotal + vat_amount
                    
                    # Update rental financials
                    rental.subtotal = base_amount
                    rental.vat = vat_amount
                    rental.total = total
                    rental.balance_due = max(0, total - rental.advance_payment)
                    
                    # Update status based on return date
                    if return_date > rental.expected_return_date:
                        rental.status = 'overdue'
                    else:
                        rental.status = 'returned'
                    
                    # Update all rental items as returned
                    for item in rental.items.all():
                        item.returned_quantity = item.quantity
                        item.return_condition = form.cleaned_data.get(f'condition_{item.id}', '')
                        item.return_notes = form.cleaned_data.get(f'notes_{item.id}', '')
                        item.save()
                    
                    rental.save()
                    
                    # Process payment if any amount was collected
                    amount_collected = form.cleaned_data['amount_to_collect']
                    if amount_collected > 0:
                        payment = Payment.objects.create(
                            rental=rental,
                            amount=amount_collected,
                            payment_method=form.cleaned_data['payment_method'],
                            payment_date=timezone.now().date(),
                            notes=f"Payment collected during return on {return_date}"
                        )
                        rental.balance_due = max(0, rental.total - rental.advance_payment - amount_collected)
                        rental.save()
                    
                    messages.success(request, f"Rental #{rental.id} has been successfully returned.")
                    return redirect('rental_detail', rental_id=rental.id)
            
            except Exception as e:
                messages.error(request, f"An error occurred while processing the return: {str(e)}")
                return redirect('rental_return', rental_id=rental.id)
    else:
        # Calculate values for the form
        today = timezone.now().date()
        overdue_days = max(0, (today - rental.expected_return_date).days)
        rental_days = (today - rental.start_date).days + 1
        
        # Calculate daily rate and base amount
        daily_rate = rental.subtotal / rental.rental_days if rental.rental_days > 0 else 0
        base_amount = daily_rate * rental_days
        
        # Calculate financials
        discount_amount = base_amount * (rental.discount / 100)
        subtotal = base_amount - discount_amount
        vat_amount = subtotal * 0.05 if rental.apply_vat else 0
        actual_total = subtotal + vat_amount
        balance_due = max(0, actual_total - rental.advance_payment)
        
        # Initialize form with rental
        form = ReturnRentalForm(
            initial={
                'return_date': today,
                'amount_to_collect': balance_due
            },
            rental=rental
        )
        
        context = {
            'rental': rental,
            'today': today,
            'overdue_days': overdue_days,
            'rental_days': rental_days,
            'daily_rate': daily_rate,
            'base_amount': base_amount,
            'discount_amount': discount_amount,
            'vat_amount': vat_amount,
            'actual_total': actual_total,
            'balance_due': balance_due,
            'form': form
        }
        return render(request, 'rental_return.html', context)
    
    
class CalculateReturnAmountView(View):
    def get(self, request, pk):
        rental = get_object_or_404(RentalAgreement, pk=pk)
        return_date = request.GET.get('return_date')
        apply_late_fees = request.GET.get('apply_late_fees', 'true') == 'true'
        
        try:
            return_date = timezone.datetime.strptime(return_date, '%Y-%m-%d').date()
            late_fee = rental.calculate_late_fee(return_date) if apply_late_fees else Decimal('0.00')
            balance_due = rental.balance_due + late_fee
            
            return JsonResponse({
                'success': True,
                'amount': str(balance_due),
                'late_fee': str(late_fee),
                'base_amount': str(rental.balance_due)
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'error': str(e)
            })


class ReturnRentalItemView(LoginRequiredMixin, UpdateView):
    model = RentalItem
    form_class = RentalItemForm
    template_name = 'rental/return_item.html'
    
    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        if self.object and not self.request.POST:
            kwargs['initial'] = {'returned_quantity': self.object.quantity}
        return kwargs

    def form_valid(self, form):
        rental_item = form.save(commit=False)
        rental_item.is_returned = True
        rental_item.save()
        
        rental_item.agreement.update_totals()
        rental_item.agreement.save()

        messages.success(self.request, f'{rental_item.product.name} returned successfully!')
        return redirect('rental_detail', pk=rental_item.agreement.pk)

class ProcessPaymentView(LoginRequiredMixin, CreateView):
    model = Payment
    form_class = PaymentForm
    template_name = 'rental/process_payment.html'

    def dispatch(self, request, *args, **kwargs):
        self.rental = get_object_or_404(RentalAgreement, pk=kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial'] = {
            'rental_agreement': self.rental,
            'amount': self.rental.balance_due,
            'payment_date': timezone.now().date()  # Add default payment date
        }
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['rental'] = self.rental
        return context

    def form_valid(self, form):
        payment = form.save(commit=False)
        payment.rental_agreement = self.rental
        payment.processed_by = self.request.user
        
        with transaction.atomic():
            payment.save()
            
            # Update rental agreement - allow overpayment
            self.rental.advance_payment = F('advance_payment') + payment.amount
            self.rental.balance_due = F('total') - F('advance_payment')
            self.rental.save()
            
            # Update invoice if exists
            if hasattr(self.rental, 'invoice'):
                invoice = self.rental.invoice
                invoice.paid_amount = F('paid_amount') + payment.amount
                invoice.save()

        messages.success(
            self.request,
            f'Payment of ${payment.amount:.2f} processed successfully!'
        )
        return redirect('rental_detail', pk=self.rental.pk)

class InvoiceDetailView(LoginRequiredMixin, DetailView):
    model = Invoice
    template_name = 'rental/invoice_detail.html'
    context_object_name = 'invoice'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['rental'] = self.object.rental_agreement
        context['payments'] = self.object.rental_agreement.payments.all().order_by('-payment_date')
        return context

def generate_invoice_pdf(request, pk):
    rental = get_object_or_404(RentalAgreement, pk=pk)
    invoice, created = Invoice.objects.get_or_create(rental_agreement=rental)
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="invoice_{invoice.invoice_number}.pdf"'
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    
    elements = []
    
    elements.append(Paragraph(f"Invoice for Rental Agreement #{rental.id}", styles['h1']))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"Invoice Number: {invoice.invoice_number}", styles['Normal']))
    elements.append(Paragraph(f"Customer: {rental.customer.name}", styles['Normal']))
    elements.append(Paragraph(f"Issue Date: {invoice.created_at.strftime('%Y-%m-%d')}", styles['Normal']))
    elements.append(Paragraph(f"Due Date: {invoice.due_date.strftime('%Y-%m-%d')}", styles['Normal']))
    elements.append(Spacer(1, 24))

    data = [['Product', 'Quantity', 'Daily Price', 'Item Total']]
    for item in rental.items.all():
        data.append([
            item.product.name,
            str(item.quantity),
            f"${item.rental_price:.2f}",
            f"${item.total_price:.2f}"
        ])
    
    table_style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
    ])
    
    item_table = Table(data)
    item_table.setStyle(table_style)
    elements.append(item_table)
    elements.append(Spacer(1, 12))

    elements.append(Paragraph(f"Subtotal: ${rental.subtotal:.2f}", styles['Normal']))
    elements.append(Paragraph(f"Discount ({rental.discount}%): -${(rental.subtotal * rental.discount / 100):.2f}", styles['Normal']))
    if rental.apply_vat:
        elements.append(Paragraph(f"VAT (5%): ${rental.vat:.2f}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total: ${rental.total:.2f}</b>", styles['Normal']))
    elements.append(Paragraph(f"Advance Payment: ${rental.advance_payment:.2f}", styles['Normal']))
    elements.append(Paragraph(f"<b>Balance Due: ${rental.balance_due:.2f}</b>", styles['Normal']))
    elements.append(Spacer(1, 24))

    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    response.write(pdf)
    return response

def generate_agreement_pdf(request, pk):
    rental = get_object_or_404(RentalAgreement, pk=pk)
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="rental_agreement_{pk}.pdf"'
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    
    elements = []
    
    elements.append(Paragraph("Rental Agreement", styles['Heading1']))
    elements.append(Spacer(1, 12))
    
    details = [
        ["Agreement #:", str(rental.id)],
        ["Customer:", rental.customer.name],
        ["Start Date:", rental.start_date.strftime('%Y-%m-%d')],
        ["Expected Return:", rental.expected_return_date.strftime('%Y-%m-%d') if rental.expected_return_date else "N/A"],
        ["Status:", rental.get_status_display()],
    ]
    
    details_table = Table(details, colWidths=[100, 300])
    details_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    elements.append(details_table)
    elements.append(Spacer(1, 20))
    
    items_data = [["Product", "Qty", "Daily Price", "Days", "Total"]]
    for item in rental.items.all():
        items_data.append([
            item.product.name,
            str(item.quantity),
            f"${item.rental_price:.2f}",
            str(rental.rental_days),
            f"${item.total_price:.2f}"
        ])
    
    items_table = Table(items_data)
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(items_table)
    elements.append(Spacer(1, 20))
    
    summary = [
        ["Subtotal:", f"${rental.subtotal:.2f}"],
        [f"Discount ({rental.discount}%):", f"-${(rental.subtotal * rental.discount / 100):.2f}"],
    ]
    
    if rental.apply_vat:
        summary.append([f"VAT (5%):", f"${rental.vat:.2f}"])
    
    summary.extend([
        ["Total:", f"${rental.total:.2f}"],
        ["Advance Payment:", f"${rental.advance_payment:.2f}"],
        ["Balance Due:", f"${rental.balance_due:.2f}"],
    ])
    
    summary_table = Table(summary, colWidths=[200, 200])
    summary_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
    ]))
    elements.append(summary_table)
    
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    response.write(pdf)
    return response

def generate_barcodes(request):
    if request.method == 'GET':
        products_without_barcodes = Product.objects.filter(barcode__isnull=True).exclude(sku__exact='')
        
        if not products_without_barcodes.exists():
            messages.info(request, "All products already have barcodes or no SKU available!")
            return redirect('product_list')
            
        barcode_type = 'code128'
        
        generated_count = 0
        failed_count = 0

        with transaction.atomic():
            for product in products_without_barcodes:
                try:
                    if not product.sku or len(product.sku) < 2:
                        messages.warning(request, f"Skipped barcode for {product.name} (SKU: '{product.sku}') - SKU is invalid for barcode generation.")
                        failed_count += 1
                        continue

                    code = barcode.get_barcode_class(barcode_type)(product.sku, writer=ImageWriter())
                    buffer = BytesIO()
                    code.write(buffer)
                    
                    filename = f"barcodes/{product.sku}_{barcode_type}.png"
                    product.barcode.save(filename, File(buffer), save=True)
                    generated_count += 1
                    
                except Exception as e:
                    messages.error(request, f"Failed to generate barcode for {product.name} (SKU: {product.sku}): {str(e)}")
                    failed_count += 1
        
        if generated_count > 0:
            messages.success(request, f"Successfully generated barcodes for {generated_count} products.")
        if failed_count > 0:
            messages.info(request, f"Failed to generate barcodes for {failed_count} products.")
        
        return redirect('product_list')
        
    return HttpResponse("Method not allowed", status=405)

class BarcodeScanView(LoginRequiredMixin, TemplateView):
    template_name = 'rental/barcode_scan.html'

from django.db.models import (
    Count, Sum, F, DecimalField, Case, When, Value
)
from django.db.models.functions import Coalesce, Cast
from django.db.models import OuterRef, Subquery, IntegerField, DecimalField, F, Sum, Count, Case, When, Value


class ProductUtilizationReportView(ListView):
    template_name = 'rental/reports/product_utilization.html'
    context_object_name = 'products'
    model = Product

    def get_queryset(self):
        queryset = super().get_queryset().annotate(
            rental_count=Count('rental_items'),

            # Sum revenue without rental_days multiplier here
            annotated_revenue=Coalesce(
                Sum(
                    F('rental_items__quantity') * 
                    F('rental_items__rental_price')
                ),
                Decimal('0.00'),
                output_field=DecimalField(max_digits=12, decimal_places=2)
            ),

            annotated_expenses=Coalesce(
                Sum('expenses__amount'),
                Decimal('0.00'),
                output_field=DecimalField(max_digits=12, decimal_places=2)
            ),

            utilization_percentage=Case(
                When(stock=0, then=Value(0, output_field=DecimalField(max_digits=5, decimal_places=2))),
                default=Cast(Count('rental_items'), output_field=DecimalField()) * 100 / Cast(F('stock'), output_field=DecimalField()),
                output_field=DecimalField(max_digits=5, decimal_places=2)
            )
        )
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Calculate rental days per RentalAgreement (or fallback to 1 if no days)
        # We calculate actual revenue multiplying rental_price * quantity * rental_days in Python here.
        products = []
        for product in context['products']:
            # Aggregate revenue manually multiplying rental_days
            revenue = Decimal('0.00')
            for item in product.rental_items.all():
                rental_days = (item.rental.expected_return_date - item.rental.start_date).days
                rental_days = rental_days if rental_days > 0 else 1
                revenue += item.rental_price * item.quantity * Decimal(rental_days)

            expenses = getattr(product, 'annotated_expenses', Decimal('0.00'))
            rental_count = getattr(product, 'rental_count', 0)

            product.template_revenue = revenue
            product.template_expenses = expenses
            product.template_net_profit = revenue - expenses
            product.template_utilization = getattr(product, 'utilization_percentage', Decimal('0.00'))

            products.append(product)

        context['products'] = products
        return context
    
from django.db.models import Max
import json
from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from django.contrib.auth.mixins import LoginRequiredMixin
from dateutil.relativedelta import relativedelta
from django.db.models.functions import TruncMonth, ExtractYear

class MonthlyRevenueDetailView(View):
    def get(self, request):
        year = request.GET.get('year')
        month = request.GET.get('month')

        payments = Payment.objects.all()

        if year:
            payments = payments.filter(payment_date__year=year)
        if month:
            payments = payments.filter(payment_date__month=month)

        # Monthly totals (used for table and chart)
        monthly_totals = (
            payments
            .annotate(month=TruncMonth('payment_date'))
            .values('month')
            .annotate(total=Sum('amount'))
            .order_by('month')
        )

        total_collected = payments.aggregate(total=Sum('amount'))['total'] or 0
        num_months = monthly_totals.count() or 1
        average_collected = total_collected / num_months

        years = Payment.objects.dates('payment_date', 'year', order='DESC')

        context = {
            'monthly_totals': monthly_totals,
            'total_collected': total_collected,
            'average_collected': average_collected,
            'selected_year': year,
            'selected_month': month,
            'years': years,
            'months': range(1, 13),
        }
        return render(request, 'rental/reports/monthly_revenue_detail.html', context)
class CustomerActivityReportView(TemplateView):
    template_name = 'rental/reports/customer_activity.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Get search query from request
        search_query = self.request.GET.get('search', '').strip()
        
        # Base queryset
        customers = Customer.objects.all()
        
        # Apply search filter if provided
        if search_query:
            customers = customers.filter(
                Q(name__icontains=search_query) |
                Q(phone__icontains=search_query) |
                Q(company__icontains=search_query)
            )
        
        # Annotate with activity data
        customers = customers.annotate(
            calculated_rental_count=Count('rentals'),
            calculated_total_spent=Coalesce(
                Sum('rentals__total', output_field=DecimalField(max_digits=12, decimal_places=2)),
                Decimal('0.00')
            ),
            calculated_active_rentals=Count(
                'rentals',
                filter=Q(rentals__status='active'),
                distinct=True
            ),
            last_rental_date=Max('rentals__start_date')
        ).order_by('-calculated_total_spent')
        
        # Prepare data for template
        customers_with_data = []
        for customer in customers:
            avg_rental = Decimal('0.00')
            if customer.calculated_rental_count > 0:
                avg_rental = customer.calculated_total_spent / customer.calculated_rental_count
            
            customer.template_data = {
                'rental_count': customer.calculated_rental_count,
                'total_spent': customer.calculated_total_spent,
                'active_rentals': customer.calculated_active_rentals,
                'avg_rental': avg_rental,
                'last_rental': customer.last_rental_date
            }
            customers_with_data.append(customer)
        
        # Prepare chart data (top 10 only)
        chart_labels = [c.name[:15] + '...' if len(c.name) > 15 else c.name for c in customers_with_data[:10]]
        chart_data = [float(c.template_data['total_spent']) for c in customers_with_data[:10]]
        
        context.update({
            'customers': customers_with_data,
            'chart_labels': json.dumps(chart_labels),
            'chart_data': chart_data,
            'search_query': search_query
        })
        return context

class ExpenseReportView(LoginRequiredMixin, TemplateView):
    template_name = 'rental/reports/expense_report.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        
        expenses = Expense.objects.all()
        if start_date and end_date:
            expenses = expenses.filter(date__range=[start_date, end_date])
        
        by_category = expenses.values('category__name').annotate(
            total=Sum('amount')
        ).order_by('-total')
        
        context['expenses'] = expenses.order_by('-date')
        context['by_category'] = by_category
        context['total'] = expenses.aggregate(total=Sum('amount'))['total'] or 0
        return context

@require_GET
def get_product_price(request, pk):
    try:
        product = Product.objects.get(pk=pk)
        return JsonResponse({'price': str(product.rental_price)})
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
        
@require_GET
def customer_detail_api(request, pk):
    try:
        customer = Customer.objects.get(pk=pk)
        data = {
            'name': customer.name,
            'email': customer.email,
            'phone': customer.phone,
            'discount_rate': float(customer.discount_rate),
        }
        return JsonResponse(data)
    except Customer.DoesNotExist:
        return JsonResponse({'error': 'Customer not found'}, status=404)

@require_GET
def product_detail_api(request, pk):
    try:
        product = Product.objects.get(pk=pk)
        data = {
            'name': product.name,
            'sku': product.sku,
            'stock': product.stock,
            'available_stock': product.available_stock,
            'rental_price': float(product.rental_price),
            'is_outsourced': product.is_outsourced,
            'purchase_year': product.purchase_year,
        }
        return JsonResponse(data)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)

from django.conf import settings
import os
from django.template.loader import get_template
from xhtml2pdf import pisa
from django.http import HttpResponse, Http404

def render_to_pdf(template_src, context_dict={}):
    template = get_template(template_src)
    html = template.render(context_dict)
    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html.encode("UTF-8")), result)
    if not pdf.err:
        return result.getvalue()
    return None

def invoice_pdf_view(request, invoice_id):
    try:
        invoice = Invoice.objects.select_related('rental_agreement__customer').prefetch_related('rental_agreement__items__product').get(pk=invoice_id)
    except Invoice.DoesNotExist:
        raise Http404("Invoice not found")

    company_logo_path = os.path.join(settings.BASE_DIR, 'static', 'images', 'company_logo.png')
    context = {
        'invoice': invoice,
        'company_logo_path': company_logo_path,
    }

    pdf_data = render_to_pdf('invoice_letterpad.html', context)
    if pdf_data:
        response = HttpResponse(pdf_data, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="invoice_{invoice.invoice_number}.pdf"'
        return response
    else:
        return HttpResponse("Failed to generate PDF", status=500)
    
class RevenueReportView(LoginRequiredMixin, TemplateView):
    template_name = 'rental/revenue_report.html'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        period = self.request.GET.get('period', 'monthly')
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        
        today = timezone.now().date()
        if not start_date:
            start_date = today - timedelta(days=30)
        if not end_date:
            end_date = today
        
        if isinstance(start_date, str):
            start_date = timezone.datetime.strptime(start_date, '%Y-%m-%d').date()
        if isinstance(end_date, str):
            end_date = timezone.datetime.strptime(end_date, '%Y-%m-%d').date()
        
        report_data = []
        if period == 'daily':
            date_range = [start_date + timedelta(days=x) for x in range((end_date - start_date).days + 1)]
            for date in date_range:
                payments = Payment.objects.filter(payment_date=date)
                rental_revenue = payments.filter(
                    rental_agreement__isnull=False
                ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
                
                report_data.append({
                    'period': date.strftime('%Y-%m-%d'),
                    'rental_revenue': rental_revenue,
                    'total_revenue': rental_revenue,
                })
        
        elif period == 'monthly':
            current_date = start_date.replace(day=1)
            while current_date <= end_date:
                next_month = current_date + relativedelta(months=1)
                month_end = min(next_month - timedelta(days=1), end_date)
                
                report = RevenueReport.objects.filter(
                    month=current_date.month,
                    year=current_date.year
                ).first()
                
                if report:
                    report_data.append({
                        'period': current_date.strftime('%Y-%m'),
                        'rental_revenue': report.rental_income,
                        'total_revenue': report.total_income,
                    })
                current_date = next_month
        
        # Calculate totals
        totals = {
            'rental': sum(item['rental_revenue'] for item in report_data),
            'total': sum(item['total_revenue'] for item in report_data),
        }
        
        # Prepare chart data
        labels = [item['period'] for item in report_data]
        rental_data = [float(item['rental_revenue']) for item in report_data]
        
        context.update({
            'period': period,
            'start_date': start_date,
            'end_date': end_date,
            'report_data': report_data,
            'totals': totals,
            'labels': labels,
            'rental_data': rental_data,
        })
        return context
    
from django.views.generic.edit import DeleteView
from django.urls import reverse_lazy

class RentalDeleteView(DeleteView):
    model = RentalAgreement
    template_name = 'rental/confirm_delete.html'  # Optional
    success_url = reverse_lazy('rental_list')