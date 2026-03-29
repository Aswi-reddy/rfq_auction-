"""
Celery configuration for rfq_auction
"""
import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rfq_auction.settings')

app = Celery('rfq_auction')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
