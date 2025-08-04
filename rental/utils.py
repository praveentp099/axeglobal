from django.db.models import Sum, Count, Q
from django.utils import timezone
from datetime import timedelta,datetime
from .models import RentalAgreement, RentalItem, Customer, Invoice
from io import BytesIO
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from django.http import HttpResponse
from django.db.models import Case, When, F
from django.db.models.fields import DurationField

from django.db.models import Sum, Count, Q, F
from django.db.models.functions import Coalesce
from django.utils import timezone
from datetime import timedelta, date
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from django.http import HttpResponse

# Import your models (adjust path if needed)
from .models import Product, Customer, RentalAgreement, RentalItem, Payment, Invoice

def calculate_dashboard_stats():
    """
    Calculates various statistics for the dashboard.
    Returns a dictionary of stats.
    """
    today = timezone.now().date()
    
    total_products = Product.objects.count()
    active_rentals = RentalAgreement.objects.filter(status='active').count()
    overdue_rentals = RentalAgreement.objects.filter(
        expected_return_date__lt=today,
        status='active'
    ).count()
    
    # Monthly Revenue (for current month)
    # This should ideally be based on when the service was provided (rental start date)
    # or invoice creation date, depending on your business logic.
    current_month_start = today.replace(day=1)
    monthly_revenue_agg = Invoice.objects.filter(
        created_at__year=today.year,
        created_at__month=today.month
    ).aggregate(total=Coalesce(Sum('total_amount'), 0.0))
    monthly_revenue = monthly_revenue_agg['total']

    return {
        'total_products': total_products,
        'active_rentals': active_rentals,
        'overdue_rentals': overdue_rentals,
        'monthly_revenue': monthly_revenue,
        'current_date': today, # Pass today's date for template logic if needed
    }

def get_customer_rental_history(customer):
    """
    Retrieves the rental history for a given customer.
    """
    return RentalAgreement.objects.filter(customer=customer).order_by('-start_date')

def get_product_utilization(product):
    """
    Calculates the utilization rate for a single product.
    This is a simplified example; real utilization might involve tracking actual rental days vs. total days.
    """
    total_rented_items = RentalItem.objects.filter(product=product).aggregate(total=Coalesce(Sum('quantity'), 0))['total']
    
    if product.stock > 0:
        # Simple utilization: (total rented count / product stock) * 100
        # More complex: sum of (item quantity * rental duration) / (stock * total duration)
        return (total_rented_items / product.stock) * 100
    return 0.0

def generate_agreement_pdf(rental_agreement):
    """
    Generates a PDF for a given RentalAgreement.
    This function should be called by the Django view.
    """
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="rental_agreement_{rental_agreement.id}.pdf"'
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    
    # Custom style for notes to allow line breaks
    notes_style = ParagraphStyle(
        name='NotesStyle',
        parent=styles['Normal'],
        leading=14,
    )

    elements = []
    
    elements.append(Paragraph(f"Rental Agreement #{rental_agreement.id}", styles['h1']))
    elements.append(Spacer(1, 12))
    
    # Customer Info
    elements.append(Paragraph("<b>Customer Details:</b>", styles['h3']))
    elements.append(Paragraph(f"Name: {rental_agreement.customer.name}", styles['Normal']))
    elements.append(Paragraph(f"Phone: {rental_agreement.customer.phone}", styles['Normal']))
    elements.append(Paragraph(f"Email: {rental_agreement.customer.email}", styles['Normal']))
    elements.append(Spacer(1, 12))

    # Rental Period
    elements.append(Paragraph("<b>Rental Period:</b>", styles['h3']))
    elements.append(Paragraph(f"Start Date: {rental_agreement.start_date.strftime('%Y-%m-%d')}", styles['Normal']))
    elements.append(Paragraph(f"Expected Return Date: {rental_agreement.expected_return_date.strftime('%Y-%m-%d')}", styles['Normal']))
    if rental_agreement.actual_return_date:
        elements.append(Paragraph(f"Actual Return Date: {rental_agreement.actual_return_date.strftime('%Y-%m-%d')}", styles['Normal']))
    elements.append(Paragraph(f"Status: {rental_agreement.get_status_display()}", styles['Normal']))
    elements.append(Spacer(1, 12))

    # Rented Items Table
    elements.append(Paragraph("<b>Rented Items:</b>", styles['h3']))
    item_data = [['Product', 'Quantity', 'Daily Rate', 'Item Total']]
    for item in rental_agreement.items.all():
        item_data.append([
            item.product.name,
            str(item.quantity),
            f"${item.rental_price:.2f}",
            f"${item.total_price:.2f}"
        ])
    
    item_table = Table(item_data, colWidths=[2*letter.inch, 0.8*letter.inch, 1*letter.inch, 1*letter.inch])
    item_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('BOX', (0, 0), (-1, -1), 1, colors.black),
    ]))
    elements.append(item_table)
    elements.append(Spacer(1, 12))

    # Financial Summary
    elements.append(Paragraph("<b>Financial Summary:</b>", styles['h3']))
    elements.append(Paragraph(f"Subtotal: ${rental_agreement.subtotal:.2f}", styles['Normal']))
    elements.append(Paragraph(f"Discount ({rental_agreement.discount}%): -${(rental_agreement.subtotal * rental_agreement.discount / 100):.2f}", styles['Normal']))
    elements.append(Paragraph(f"VAT (5%): ${rental_agreement.vat:.2f}", styles['Normal']))
    elements.append(Paragraph(f"<b>Total: ${rental_agreement.total:.2f}</b>", styles['Normal']))
    elements.append(Paragraph(f"Advance Payment: ${rental_agreement.advance_payment:.2f}", styles['Normal']))
    elements.append(Paragraph(f"<b>Balance Due: ${rental_agreement.balance_due:.2f}</b>", styles['Normal']))
    elements.append(Spacer(1, 12))

    # Notes
    if rental_agreement.notes:
        elements.append(Paragraph("<b>Notes:</b>", styles['h3']))
        elements.append(Paragraph(rental_agreement.notes, notes_style))
        elements.append(Spacer(1, 12))
    
    # Terms and Conditions (Placeholder - add your actual T&Cs)
    elements.append(Paragraph("<b>Terms and Conditions:</b>", styles['h3']))
    elements.append(Paragraph("1. All equipment remains the property of the rental company.", styles['Normal']))
    elements.append(Paragraph("2. The renter is responsible for any damages or loss.", styles['Normal']))
    elements.append(Paragraph("3. Late returns may incur additional charges.", styles['Normal']))
    elements.append(Spacer(1, 24))

    # Signatures
    elements.append(Paragraph("_________________________                           _________________________", styles['Normal']))
    elements.append(Paragraph("Customer Signature                                          Company Representative", styles['Normal']))
    
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    response.write(pdf)
    return response

def get_customer_rental_history(customer, period=None):
    rentals = RentalAgreement.objects.filter(customer=customer)
    
    if period:
        today = datetime.today().date()
        if period == 'week':
            start_date = today - timedelta(days=7)
        elif period == 'month':
            start_date = today - timedelta(days=30)
        elif period == 'quarter':
            start_date = today - timedelta(days=90)
        elif period == 'year':
            start_date = today - timedelta(days=365)
        rentals = rentals.filter(start_date__gte=start_date)
    
    return rentals

def get_product_utilization(product):
    stats = {
        'total_rentals': RentalItem.objects.filter(product=product).count(),
        'total_revenue': RentalItem.objects.filter(product=product).aggregate(
            Sum('rental_price')
        )['rental_price__sum'] or 0,
        'current_availability': product.stock - RentalItem.objects.filter(
            product=product,
            agreement__status='active'
        ).count()
    }
    return stats

def calculate_dashboard_stats():
    today = datetime.today().date()
    return {
        'monthly_revenue': Invoice.objects.filter(
            issue_date__month=today.month,
            issue_date__year=today.year
        ).aggregate(Sum('total_amount'))['total_amount__sum'] or 0,
        'active_customers': Customer.objects.filter(
            RentalAgreement__status='active'
        ).distinct().count(),
        'products_rented': RentalItem.objects.filter(
            agreement__status='active'
        ).count(),
        'overdue_rentals': RentalAgreement.objects.filter(
            expected_return_date__lt=today,
            status='active'
        ).count()
    }


def generate_agreement_pdf(agreement):
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="rental_agreement_{agreement.id}.pdf"'
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    
    # Custom styles
    styles.add(ParagraphStyle(
        name='Title',
        fontSize=18,
        alignment=1,
        spaceAfter=12
    ))
    
    styles.add(ParagraphStyle(
        name='Header',
        fontSize=12,
        spaceAfter=6
    ))
    
    elements = []
    
    # Title
    elements.append(Paragraph("EQUIPMENT RENTAL AGREEMENT", styles['Title']))
    elements.append(Spacer(1, 12))
    
    # Agreement details
    details = [
        ['Agreement ID:', agreement.id],
        ['Date:', agreement.start_date.strftime('%Y-%m-%d')],
        ['Customer:', agreement.customer.name],
        ['Company:', agreement.customer.company or 'N/A'],
        ['Contact:', agreement.customer.phone],
        ['Email:', agreement.customer.email],
        ['Discount:', f"{agreement.discount}%"],
        ['Status:', agreement.get_status_display()],
    ]
    
    if agreement.expected_return_date:
        details.append(['Expected Return:', agreement.expected_return_date.strftime('%Y-%m-%d')])
    
    t = Table(details, colWidths=[120, 300])
    t.setStyle(TableStyle([
        ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
        ('ALIGN', (0,0), (0,-1), 'RIGHT'),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 24))
    
    # Items rented
    elements.append(Paragraph("RENTED EQUIPMENT", styles['Header']))
    item_data = [['Product', 'Quantity', 'Daily Rate', 'Total']]
    total = 0
    for item in agreement.items.all():
        item_total = item.quantity * item.rental_price
        total += item_total
        item_data.append([
            item.product.name,
            str(item.quantity),
            f"${item.rental_price:.2f}",
            f"${item_total:.2f}"
        ])
    
    # Apply discount
    if agreement.discount > 0:
        discount_amount = total * (agreement.discount / 100)
        item_data.append(['', '', 'Discount:', f"-${discount_amount:.2f}"])
        total -= discount_amount
    
    item_data.append(['', '', 'Grand Total:', f"${total:.2f}"])
    
    t2 = Table(item_data, colWidths=[250, 70, 70, 70])
    t2.setStyle(TableStyle([
        ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
        ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('ALIGN', (2,0), (-1,-1), 'RIGHT'),
    ]))
    elements.append(t2)
    elements.append(Spacer(1, 24))
    
    # Terms and conditions
    elements.append(Paragraph("TERMS AND CONDITIONS", styles['Header']))
    terms = [
        "1. The equipment must be returned in the same condition as when rented.",
        "2. Any damage to equipment will result in additional charges.",
        "3. Late returns will incur additional daily rental fees.",
        "4. The renter is responsible for equipment loss or theft.",
        "5. Payment is due upon equipment return."
    ]
    
    for term in terms:
        elements.append(Paragraph(term, styles['Normal']))
        elements.append(Spacer(1, 6))
    
    elements.append(Spacer(1, 24))
    
    # Signature lines
    signature_data = [
        ['Renter Signature:', '', 'Date:', ''],
        ['', '', '', ''],
        ['AxeGlobal Representative:', '', 'Date:', '']
    ]
    
    t3 = Table(signature_data, colWidths=[150, 100, 70, 100])
    t3.setStyle(TableStyle([
        ('FONT', (0,0), (-1,-1), 'Helvetica', 10),
        ('LINEABOVE', (1,1), (1,1), 1, colors.black),
        ('LINEABOVE', (3,1), (3,1), 1, colors.black),
        ('LINEABOVE', (1,3), (1,3), 1, colors.black),
        ('LINEABOVE', (3,3), (3,3), 1, colors.black),
    ]))
    elements.append(t3)
    
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    response.write(pdf)
    return response

def generate_invoice_pdf(invoice):
    # Similar structure to agreement but with payment details
    # Implementation would be similar with invoice-specific fields
    pass