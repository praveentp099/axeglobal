from celery import Celery
from celery.schedules import crontab

app = Celery('axeglobal')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'send-rental-reminders': {
        'task': 'rental.tasks.send_rental_reminders',
        'schedule': crontab(hour=8, minute=0),  # Daily at 8 AM
    },
    'update-overdue-rentals': {
        'task': 'rental.management.commands.update_overdue',
        'schedule': crontab(hour=0, minute=0),  # Daily at midnight
    },
}