from celery import shared_task
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from .models import RentalAgreement

@shared_task
def send_rental_reminders():
    # Reminders for rentals due tomorrow
    tomorrow = timezone.now().date() + timezone.timedelta(days=1)
    due_rentals = RentalAgreement.objects.filter(
        expected_return_date=tomorrow,
        status='active'
    )
    
    for rental in due_rentals:
        subject = f"Equipment Return Reminder - Rental #{rental.id}"
        message = render_to_string('rental/emails/return_reminder.txt', {
            'rental': rental,
            'customer': rental.customer
        })
        send_mail(
            subject,
            message,
            'noreply@axeglobal.com',
            [rental.customer.email],
            fail_silently=False,
        )
    
    # Overdue reminders
    overdue_rentals = RentalAgreement.objects.filter(
        expected_return_date__lt=timezone.now().date(),
        status='active'
    )
    
    for rental in overdue_rentals:
        subject = f"Overdue Equipment - Rental #{rental.id}"
        message = render_to_string('rental/emails/overdue_notification.txt', {
            'rental': rental,
            'customer': rental.customer
        })
        send_mail(
            subject,
            message,
            'noreply@axeglobal.com',
            [rental.customer.email, 'billing@axeglobal.com'],
            fail_silently=False,
        )
    
    return f"Sent {due_rentals.count()} reminders and {overdue_rentals.count()} overdue notifications"