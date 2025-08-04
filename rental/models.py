from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.utils import timezone
import barcode
from barcode.writer import ImageWriter
from io import BytesIO
from django.core.files import File
from django.db.models import Sum, F
from datetime import date
from django.conf import settings

class ExpenseCategory(models.Model):
    CATEGORY_CHOICES = [
        ('electrical', 'Electrical'),
        ('rent', 'Rent'),
        ('recharge', 'Recharge'),
        ('salary', 'Salary'),
        ('maintenance', 'Maintenance & Service'),
        ('purchases', 'Purchases'),
        ('transportation', 'Transportation'),
        ('mechanical', 'Mechanical'),
        ('misc', 'Miscellaneous'),
    ]
    
    name = models.CharField(max_length=100, choices=CATEGORY_CHOICES, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "Expense Categories"
        ordering = ['name']

    def __str__(self):
        return self.get_name_display()

class Expense(models.Model):
    date = models.DateField(default=timezone.now)
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT)
    description = models.TextField()
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0.01)])
    product = models.ForeignKey('Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses')
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-date']
        verbose_name_plural = "Expenses"

    def __str__(self):
        return f"{self.date} - {self.category}: {self.description[:20]}"

    def save(self, *args, **kwargs):
        if not self.pk and not self.created_by_id:
            from django.contrib.auth import get_user
            user = get_user(self._request)
            if user.is_authenticated:
                self.created_by = user
        super().save(*args, **kwargs)

class Customer(models.Model):
    name = models.CharField(max_length=200)
    email = models.EmailField(blank=True, null=True)
    phone = models.CharField(max_length=20)
    address = models.TextField(blank=True)
    company = models.CharField(max_length=200, blank=True, null=True)
    tax_id = models.CharField(max_length=50, blank=True, null=True)
    discount_rate = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=0.0,
        validators=[MinValueValidator(0), MaxValueValidator(100)]
    )
    join_date = models.DateField(auto_now_add=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['name']

    @property
    def payment_history(self):
        return Payment.objects.filter(
            rental_agreement__customer=self
        ).order_by('-payment_date')
    
    @property
    def total_payments(self):
        return self.payment_history.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')

    def __str__(self):
        return self.name

    @property
    def active_rentals(self):
        return self.rentals.filter(status='active').count()

    @property
    def total_spent(self):
        return self.rentals.aggregate(total=Sum('total'))['total'] or Decimal('0.00')

class Product(models.Model):
    CONDITION_CHOICES = [
        ('new', 'Brand New'),
        ('excellent', 'Excellent - Like New'),
        ('good', 'Good - Minor Wear'),
        ('fair', 'Fair - Visible Wear'),
        ('poor', 'Poor - Needs Repair'),
    ]
    
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    
    # Fields for both types of products
    stock = models.PositiveIntegerField(default=1)
    is_rentable = models.BooleanField(default=True)
    is_sellable = models.BooleanField(default=False)
    is_outsourced = models.BooleanField(default=False)
    
    # Fields for owned products
    purchase_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        null=True,
        blank=True
    )
    rental_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)]
    )
    
    # Fields for outsourced products
    outsourced_purchase_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Supplier Cost"
    )
    outsourced_rental_price = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Customer Rental Price",
        validators=[MinValueValidator(0)]
    )
    
    condition = models.CharField(
        max_length=20,
        choices=CONDITION_CHOICES,
        default='good',
        verbose_name="Initial Condition"
    )
    
    current_condition = models.CharField(
        max_length=20,
        choices=CONDITION_CHOICES,
        blank=True,
        null=True,
        verbose_name="Current Condition"
    )
    last_service_date = models.DateField(null=True, blank=True)
    next_service_date = models.DateField(null=True, blank=True)
    purchase_year = models.PositiveIntegerField(
        null=True, 
        blank=True,
        validators=[
            MinValueValidator(1900),
            MaxValueValidator(timezone.now().year)
        ]
    )
    barcode = models.ImageField(upload_to='barcodes/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    

    def clean(self):
        if self.is_outsourced:
            if not self.outsourced_purchase_price or not self.outsourced_rental_price:
                raise ValidationError("Outsourced products must have both supplier cost and customer rental price.")
        else:
            if not self.purchase_price or not self.rental_price:
                raise ValidationError("Owned products must have both purchase price and rental price.")

    @property
    def effective_rental_price(self):
        return self.outsourced_rental_price if self.is_outsourced else self.rental_price

    @property
    def profit_per_rental_day(self):
        if self.is_outsourced:
            return self.outsourced_rental_price - self.outsourced_purchase_price
        return self.rental_price

    @property
    def investment_value(self):
        if self.is_outsourced or not self.purchase_price:
            return Decimal('0.00')
        try:
            return Decimal(str(self.stock)) * self.purchase_price
        except (TypeError, ValueError):
            return Decimal('0.00')

    class Meta:
        ordering = ['name']

    def save(self, *args, **kwargs):
        if self.pk:
            old = Product.objects.get(pk=self.pk)
            if old.sku != self.sku and old.barcode:
                old.barcode.delete(save=False)
        
        if not self.barcode and self.sku:
            CODE128 = barcode.get_barcode_class('code128')
            code = CODE128(self.sku, writer=ImageWriter())
            buffer = BytesIO()
            code.write(buffer)
            self.barcode.save(f'{self.sku}.png', File(buffer), save=False)
        super().save(*args, **kwargs)
    
    @property
    def rented_count(self):
        return self.rental_items.filter(
            returned_quantity__lt=F('quantity'),
            rental__status='active'
        ).aggregate(total=models.Sum('quantity'))['total'] or 0
    
    @property
    def available_stock(self):
        return self.stock - self.rented_count
    
    @property
    def total_expenses(self):
        return self.expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    @property
    def net_revenue(self):
        revenue = RentalItem.objects.filter(
            product=self
        ).aggregate(
            total=Sum(
                F('quantity') * F('rental_price') * F('agreement__rental_days'),
                output_field=models.DecimalField()
            )
        )['total'] or Decimal('0.00')
        return revenue - self.total_expenses

    def __str__(self):
        return self.name

class RentalAgreement(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('returned', 'Returned'),
        ('overdue', 'Overdue'),
        ('cancelled', 'Cancelled'),
    ]
    
    customer = models.ForeignKey('Customer', on_delete=models.PROTECT, related_name='rentals')
    start_date = models.DateField()
    expected_return_date = models.DateField()
    actual_return_date = models.DateField(null=True, blank=True)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    vat = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    advance_payment = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    balance_due = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    apply_vat = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def rental_days(self):
        if self.actual_return_date:
            return (self.actual_return_date - self.start_date).days + 1
        return (self.expected_return_date - self.start_date).days + 1
    
    def get_daily_rate_for_product(self, product_id):
        """Get the daily rate for a specific product in this rental"""
        item = self.items.filter(product_id=product_id).first()
        if item:
            return item.rental_price
        return Decimal('0.00')
    
    def update_totals(self):
        """Update all financial calculations"""
        self.subtotal = sum(item.total_price for item in self.items.all())
        
        if self.apply_vat:
            self.vat = self.subtotal * Decimal('0.05')
        else:
            self.vat = Decimal('0.00')
            
        discount_amount = self.subtotal * (self.discount / Decimal('100'))
        self.total = (self.subtotal - discount_amount) + self.vat
        
        # Calculate paid amount from all payments
        self.paid_amount = self.payments.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0.00')
        
        self.balance_due = max(Decimal('0.00'), self.total - self.paid_amount)
        self.save()
        
        # Update related invoice if exists
        if hasattr(self, 'invoice'):
            self.invoice.update_payment_status()

    def total_days(self):
        if self.actual_return_date:
            return (self.actual_return_date - self.start_date).days + 1
        return self.rental_days

    def total_rental_amount(self):
        return sum(item.total_rental_amount() for item in self.items.all())

    @property
    def is_overdue(self):
        return self.status == 'active' and timezone.now().date() > self.expected_return_date

    def __str__(self):
        return f"Rental #{self.id} - {self.customer.name}"


class RentalItem(models.Model):
    rental = models.ForeignKey(RentalAgreement, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='rental_items')
    quantity = models.PositiveIntegerField(default=1)
    rental_price = models.DecimalField(max_digits=10, decimal_places=2)
    returned_quantity = models.PositiveIntegerField(default=0)
    return_condition = models.CharField(max_length=100, blank=True)
    return_notes = models.TextField(blank=True)

    @property
    def total_price(self):
        return self.rental_price * self.quantity * self.rental.rental_days

    @property
    def is_returned(self):
        return self.returned_quantity >= self.quantity

    def __str__(self):
        return f"{self.product.name} ({self.quantity}) in Rental #{self.rental.id}"

    class Meta:
        ordering = ['rental__start_date']

    def clean(self):
        if not self.product_id:
            raise ValidationError("Product must be selected")
        if self.product and not self.product.is_rentable:
            raise ValidationError("This product is not available for rent")
        if self.quantity > self.product.available_stock and not self.is_returned:
            raise ValidationError(f"Only {self.product.available_stock} available in stock")
    


    def save(self, *args, **kwargs):
        if not self.rental_price:
            # Use the effective rental price from the product
            self.rental_price = self.product.effective_rental_price
        super().save(*args, **kwargs)

    def calculate_profit(self):
        if self.product.is_outsourced:
            rental_days = self.rental.rental_days
            return (self.product.outsourced_rental_price - self.product.outsourced_purchase_price) * self.quantity * rental_days
        return self.total_price

    def get_overdue_days(self):
        if self.rental.is_overdue:
            return (timezone.now().date() - self.agreement.expected_return_date).days
        return 0
    
    def total_rental_amount(self):
        return self.rental_price * self.quantity * self.rental.total_days()
    
    def __str__(self):
        return f"{self.product.name if self.product_id else 'Unknown Product'} x{self.quantity}"

class Invoice(models.Model):
    PAYMENT_STATUS_CHOICES = [
        ('paid', 'Paid'),
        ('partial', 'Partial Payment'),
        ('unpaid', 'Unpaid'),
    ]
    
    rental_agreement = models.OneToOneField(
        RentalAgreement,
        on_delete=models.CASCADE,
        related_name='invoice'
    )
    invoice_number = models.CharField(max_length=50, unique=True)
    issue_date = models.DateField(auto_now_add=True)
    due_date = models.DateField()
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='unpaid'
    )
    
    def update_payment_status(self):
        """Update status based on payments"""
        if self.paid_amount >= self.total_amount:
            self.payment_status = 'paid'
        elif self.paid_amount > 0:
            self.payment_status = 'partial'
        else:
            self.payment_status = 'unpaid'
        self.save()

class InvoiceLineItem(models.Model):
    ITEM_TYPE_CHOICES = [
        ('rental', 'Rental Charge'),
        ('late_fee', 'Late Fee'),
        ('damage', 'Damage Charge'),
        ('discount', 'Discount'),
        ('adjustment', 'Adjustment'),
        ('vat', 'VAT'),
        ('payment', 'Payment'),
    ]
    
    invoice = models.ForeignKey(
        Invoice,
        on_delete=models.CASCADE,
        related_name='line_items'
    )
    description = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    item_type = models.CharField(max_length=20, choices=ITEM_TYPE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)

class Payment(models.Model):
    PAYMENT_METHODS = [
        ('cash', 'Cash'),
        ('card', 'Credit Card'),
        ('bank', 'Bank Transfer'),
    ]
    
    rental_agreement = models.ForeignKey(
        RentalAgreement, 
        on_delete=models.CASCADE,
        related_name='payments'
    )
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    payment_date = models.DateField(db_index=True)  # Now uses return date
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS)
    notes = models.TextField(blank=True)
    receipt_number = models.CharField(max_length=50, unique=True, null=True, blank=True)
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True
    )

    class Meta:
        ordering = ['-payment_date']
    
    def save(self, *args, **kwargs):
        if not self.receipt_number:
            self.receipt_number = f"PYMT-{timezone.now().strftime('%Y%m%d%H%M%S')}"
        super().save(*args, **kwargs)
        self.rental_agreement.update_totals()

class RevenueReport(models.Model):
    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()
    rental_income = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    other_income = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total_income = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('month', 'year')
        ordering = ['-year', '-month']

    def __str__(self):
        return f"{self.month}/{self.year} - ${self.total_income}"

    @classmethod
    def get_current_month_report(cls):
        now = timezone.now()
        report, created = cls.objects.get_or_create(
            month=now.month,
            year=now.year,
            defaults={
                'rental_income': Decimal('0.00'),
                'other_income': Decimal('0.00'),
                'total_income': Decimal('0.00')
            }
        )
        return report