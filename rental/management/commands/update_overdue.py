from django.core.management.base import BaseCommand
from django.utils import timezone
from rental.models import RentalAgreement

class Command(BaseCommand):
    help = 'Updates the status of overdue rental agreements'
    
    def handle(self, *args, **kwargs):
        today = timezone.now().date()
        overdue_rentals = RentalAgreement.objects.filter(
            expected_return_date__lt=today,
            status='active'
        )
        
        count = overdue_rentals.update(status='overdue')
        
        self.stdout.write(self.style.SUCCESS(
            f'Successfully marked {count} rentals as overdue'
        ))