from django.views.generic import TemplateView, ListView, DetailView
from django.utils import timezone
from rental.models import Invoice,RentalAgreement,Payment,RentalItem
from django.db.models import Sum, Count
from django.db.models.functions import TruncMonth, TruncQuarter, TruncYear, ExtractWeek, ExtractYear
from datetime import datetime, timedelta
from decimal import Decimal
import json
from datetime import date
from django.db.models import Sum, F, ExpressionWrapper, DecimalField
from django.contrib.auth.mixins import LoginRequiredMixin
from dateutil.relativedelta import relativedelta
from django.db.models.functions import TruncDay
from django.db.models.functions import TruncMonth, TruncYear


class FinancialDashboardView(TemplateView):
    template_name = 'accounts/financial_dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        today = timezone.now().date()
        last_month = today - timedelta(days=30)
        year_start = date(today.year, 1, 1)
        
        # Revenue Calculations
        monthly_revenue = Invoice.objects.filter(
            issue_date__year=today.year,
            issue_date__month=today.month
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        
        last_month_revenue = Invoice.objects.filter(
            issue_date__year=last_month.year,
            issue_date__month=last_month.month
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        
        ytd_revenue = Invoice.objects.filter(
            issue_date__gte=year_start
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        
        last_year_ytd = Invoice.objects.filter(
            issue_date__gte=year_start - timedelta(days=365),
            issue_date__lte=today - timedelta(days=365)
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        
        # Outstanding Invoices
        outstanding_invoices = Invoice.objects.filter(
            payment_status__in=['unpaid', 'partial']
        ).count()
        
        last_month_outstanding = Invoice.objects.filter(
            payment_status__in=['unpaid', 'partial'],
            issue_date__lt=last_month
        ).count()
        
        # Receivables
        total_receivables = Invoice.objects.filter(
            payment_status__in=['unpaid', 'partial']
        ).aggregate(total=Sum(F('total_amount') - F('paid_amount')))['total'] or Decimal('0.00')
        
        last_month_receivables = Invoice.objects.filter(
            payment_status__in=['unpaid', 'partial'],
            issue_date__lt=last_month
        ).aggregate(total=Sum(F('total_amount') - F('paid_amount')))['total'] or Decimal('0.00')
        
        # Change Calculations
        revenue_change = self.calculate_percentage_change(last_month_revenue, monthly_revenue)
        ytd_change = self.calculate_percentage_change(last_year_ytd, ytd_revenue)
        outstanding_change = self.calculate_percentage_change(last_month_outstanding, outstanding_invoices)
        receivables_change = self.calculate_percentage_change(last_month_receivables, total_receivables)
        
        # Recent Data
        recent_invoices = Invoice.objects.select_related(
            'rental_agreement__customer'
        ).order_by('-issue_date')[:10]
        
        top_outstanding = Invoice.objects.filter(
            payment_status__in=['unpaid', 'partial']
        ).annotate(
            due_amount=F('total_amount') - F('paid_amount')
        ).order_by('-due_amount')[:5]
        
        # Revenue by Category (example - adjust based on your model)
        category_data = RentalAgreement.objects.values(
            'customer__company'
        ).annotate(
            total=Sum('total')
        ).order_by('-total')[:8]
        
        # Chart Data
        revenue_labels, revenue_data = self.get_revenue_chart_data()
        
        context.update({
            'monthly_revenue': monthly_revenue,
            'ytd_revenue': ytd_revenue,
            'outstanding_invoices': outstanding_invoices,
            'total_receivables': total_receivables,
            'revenue_change': revenue_change,
            'ytd_change': ytd_change,
            'outstanding_change': outstanding_change,
            'receivables_change': receivables_change,
            'recent_invoices': recent_invoices,
            'top_outstanding': top_outstanding,
            'category_labels': [item['customer__company'] or 'Individual' for item in category_data],
            'category_data': [float(item['total']) for item in category_data],
            'revenue_labels': revenue_labels,
            'revenue_data': revenue_data,
        })
        return context

    def calculate_percentage_change(self, old_value, new_value):
        if not old_value or old_value == 0:
            return 0
        return ((new_value - old_value) / old_value) * 100

    def get_revenue_chart_data(self):
        today = timezone.now().date()
        months = []
        revenue = []
        
        for i in range(6, -1, -1):  # Last 6 months + current month
            month_date = today - timedelta(days=30*i)
            month_name = month_date.strftime('%b %Y')
            months.append(month_name)
            
            monthly_total = Invoice.objects.filter(
                issue_date__year=month_date.year,
                issue_date__month=month_date.month
            ).aggregate(total=Sum('total_amount'))['total'] or 0
            
            revenue.append(float(monthly_total))
        
        return months, revenue


class RevenueReportView(LoginRequiredMixin, TemplateView):
    template_name = 'rental/revenue_report.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        period = self.request.GET.get('period', 'monthly')
        start_date, end_date = self._get_date_range()

        # Get payment data grouped by period
        payments = Payment.objects.filter(
            payment_date__gte=start_date,
            payment_date__lte=end_date
        )
        
        report_data = self._group_payments(payments, period)
        totals = self._calculate_totals(report_data)

        context.update({
            'period': period,
            'start_date': start_date,
            'end_date': end_date,
            'report_data': report_data,
            'totals': totals,
            'chart_data': self._prepare_chart_data(report_data)
        })
        return context

    def _get_date_range(self):
        today = timezone.now().date()
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        
        if not start_date:
            start_date = today - relativedelta(years=1)
        else:
            start_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        
        if not end_date:
            end_date = today
        else:
            end_date = datetime.strptime(end_date, '%Y-%m-%d').date()
            
        return start_date, end_date

    def _group_payments(self, payments, period):
        if period == 'daily':
            return payments.annotate(
                period=TruncDay('payment_date')
            ).values('period').annotate(
                total=Sum('amount')
            ).order_by('period')
        
        elif period == 'weekly':
            return payments.annotate(
                week=ExtractWeek('payment_date'),
                year=ExtractYear('payment_date')
            ).values('year', 'week').annotate(
                total=Sum('amount')
            ).order_by('year', 'week')
        
        elif period == 'monthly':
            return payments.annotate(
                period=TruncMonth('payment_date')
            ).values('period').annotate(
                total=Sum('amount')
            ).order_by('period')
        
        elif period == 'quarterly':
            return payments.annotate(
                period=TruncQuarter('payment_date')
            ).values('period').annotate(
                total=Sum('amount')
            ).order_by('period')
        
        else:  # yearly
            return payments.annotate(
                period=TruncYear('payment_date')
            ).values('period').annotate(
                total=Sum('amount')
            ).order_by('period')

    def _calculate_totals(self, report_data):
        total = sum(item['total'] for item in report_data)
        return {
            'total': total,
            'avg_daily': total / len(report_data) if report_data else 0
        }

    def _prepare_chart_data(self, report_data):
        return {
            'labels': [self._format_period(item, self.request.GET.get('period')) for item in report_data],
            'data': [float(item['total']) for item in report_data]
        }

    def _format_period(self, item, period_type):
        date_obj = item.get('period') or datetime(item['year'], 1, 1)
        
        if period_type == 'daily':
            return date_obj.strftime('%b %d')
        elif period_type == 'weekly':
            return f"Week {item['week']}, {item['year']}"
        elif period_type == 'monthly':
            return date_obj.strftime('%b %Y')
        elif period_type == 'quarterly':
            quarter = (date_obj.month - 1) // 3 + 1
            return f"Q{quarter} {date_obj.year}"
        else:
            return date_obj.strftime('%Y')


class InvoiceListView(ListView):
    model = Invoice
    template_name = 'accounts/invoice_list.html'
    context_object_name = 'invoices'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset()
        
        # Add filters if needed
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(payment_status=status)
            
        return queryset.select_related('rental_agreement__customer')


class UserProfileView(TemplateView):
    template_name = 'accounts/user_profile.html'

class InvoiceDetailView(LoginRequiredMixin, DetailView):
    model = Invoice
    template_name = 'accounts/invoice_detail.html'
    context_object_name = 'invoice'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['rental'] = self.object.rental_agreement
        context['payments'] = self.object.rental_agreement.payments.all().order_by('-payment_date')
        return context