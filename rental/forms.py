from django import forms
from django.forms import inlineformset_factory, BaseInlineFormSet
from .models import *
from io import TextIOWrapper
import csv

class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = '__all__'
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
            'purchase_year': forms.NumberInput(attrs={
                'min': 1900,
                'max': timezone.now().year
            }),
            'purchase_price': forms.NumberInput(attrs={
                'step': '0.01',
                'min': '0.01',
                'class': 'owned-product-field form-control'
            }),
            'rental_price': forms.NumberInput(attrs={
                'step': '0.01',
                'min': '0.01',
                'class': 'owned-product-field form-control'
            }),
            'outsourced_purchase_price': forms.NumberInput(attrs={
                'step': '0.01',
                'min': '0.01',
                'class': 'outsourced-product-field form-control'
            }),
            'outsourced_rental_price': forms.NumberInput(attrs={
                'step': '0.01',
                'min': '0.01',
                'class': 'outsourced-product-field form-control'
            }),
            'condition': forms.Select(attrs={
                'class': 'form-select'
            }),
            'current_condition': forms.Select(attrs={
                'class': 'form-select'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.fields['is_outsourced'].widget.attrs.update({
            'class': 'form-check-input',
            'onchange': 'toggleOutsourcedFields()'
        })
        
        # Initialize required fields based on product type
        if self.instance and self.instance.pk:
            if self.instance.is_outsourced:
                self.fields['outsourced_purchase_price'].required = True
                self.fields['outsourced_rental_price'].required = True
            else:
                self.fields['purchase_price'].required = True
                self.fields['rental_price'].required = True

    def clean(self):
        cleaned_data = super().clean()
        is_outsourced = cleaned_data.get('is_outsourced', False)
        
        if is_outsourced:
            self._validate_outsourced_product(cleaned_data)
        else:
            self._validate_owned_product(cleaned_data)
        
        return cleaned_data

    def _validate_owned_product(self, cleaned_data):
        if not cleaned_data.get('purchase_price'):
            self.add_error('purchase_price', 'Purchase price is required for owned products')
        if not cleaned_data.get('rental_price'):
            self.add_error('rental_price', 'Rental price is required for owned products')
        
        cleaned_data['outsourced_purchase_price'] = None
        cleaned_data['outsourced_rental_price'] = None

    def _validate_outsourced_product(self, cleaned_data):
        supplier_cost = cleaned_data.get('outsourced_purchase_price')
        rental_price = cleaned_data.get('outsourced_rental_price')
        
        if not supplier_cost:
            self.add_error('outsourced_purchase_price', 'Supplier cost is required')
        if not rental_price:
            self.add_error('outsourced_rental_price', 'Customer rental price is required')
        elif supplier_cost and rental_price <= supplier_cost:
            self.add_error(
                'outsourced_rental_price',
                'Customer rental price must be greater than supplier cost'
            )
        
        cleaned_data['purchase_price'] = None
        cleaned_data['rental_price'] = None

class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = '__all__'
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

class RentalAgreementForm(forms.ModelForm):
    class Meta:
        model = RentalAgreement
        fields = [
            'customer', 'start_date', 'expected_return_date', 
            'discount', 'notes', 'advance_payment'
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'expected_return_date': forms.DateInput(attrs={'type': 'date'}),
            'notes': forms.Textarea(attrs={'rows': 4}),
        }

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        expected_return_date = cleaned_data.get('expected_return_date')
        
        if start_date and expected_return_date and start_date > expected_return_date:
            raise ValidationError("Start date must be before expected return date")
        
        return cleaned_data

class RentalItemForm(forms.ModelForm):
    class Meta:
        model = RentalItem
        fields = ['product', 'quantity', 'rental_price']
        widgets = {
            'rental_price': forms.NumberInput(attrs={'step': '0.01'}),
            'quantity': forms.NumberInput(attrs={'min': '1'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].queryset = self.fields['product'].queryset.filter(is_rentable=True)


# rental/forms.py
class PaymentForm(forms.ModelForm):
    payment_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date'}),
        initial=timezone.now().date()
    )
    
    class Meta:
        model = Payment
        fields = ['amount', 'payment_date', 'payment_method', 'notes']
        widgets = {
            'amount': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'min': '0.01'
            }),
            'payment_method': forms.Select(attrs={
                'class': 'form-select'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3
            }),
        }

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError("Payment amount must be greater than zero")
        return amount

class ProductImportForm(forms.Form):
    csv_file = forms.FileField(label='CSV File')

    def process_import(self):
        csv_file = TextIOWrapper(
            self.cleaned_data['csv_file'].file,
            encoding='utf-8'
        )
        reader = csv.DictReader(csv_file)
        created_count = 0
        errors = []
        
        for row in reader:
            try:
                Product.objects.create(
                    name=row['name'],
                    sku=row['sku'],
                    description=row.get('description', ''),
                    purchase_price=row.get('purchase_price', 0),
                    rental_price=row['rental_price'],
                    stock=row['stock'],
                    is_rentable=row['is_rentable'].lower() == 'true',
                    is_sellable=row.get('is_sellable', 'false').lower() == 'true',
                    is_outsourced=row.get('is_outsourced', 'false').lower() == 'true',
                    purchase_year=row.get('purchase_year')
                )
                created_count += 1
            except Exception as e:
                errors.append(f"Error importing {row.get('name')}: {str(e)}")
        
        return created_count, errors

class ProductStockForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['stock']

class ExpenseCategoryForm(forms.ModelForm):
    class Meta:
        model = ExpenseCategory
        fields = '__all__'
        widgets = {
            'description': forms.Textarea(attrs={'rows': 3}),
        }

class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = '__all__'
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['product'].queryset = Product.objects.filter(is_outsourced=True)

RentalItemFormSet = inlineformset_factory(
    RentalAgreement,
    RentalItem,
    form=RentalItemForm,
    formset=BaseInlineFormSet,
    extra=1,
    can_delete=True
)

class ReturnRentalForm(forms.Form):
    return_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
        initial=timezone.now().date(),
        required=True
    )
    amount_to_collect = forms.DecimalField(
        max_digits=10, 
        decimal_places=2,
        min_value=0,
        required=True
    )
    payment_method = forms.ChoiceField(
        choices=Payment.PAYMENT_METHODS,  # make sure Payment.PAYMENT_METHODS is imported
        initial='cash',
        required=True
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea
    )

    def __init__(self, *args, **kwargs):
        # POP the rental kwarg before calling super()
        self.rental = kwargs.pop('rental', None)
        super().__init__(*args, **kwargs)

        if self.rental:
            self.fields['amount_to_collect'].initial = getattr(self.rental, 'balance_due', Decimal('0.00'))

    def clean_return_date(self):
        return_date = self.cleaned_data.get('return_date')
        if not return_date:
            raise forms.ValidationError("Return date is required")

        if self.rental and return_date < self.rental.start_date:
            raise forms.ValidationError("Return date cannot be before rental start date")
            
        return return_date
