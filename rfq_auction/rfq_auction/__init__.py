# This will be run when Django starts
# Celery is optional - only import if available
try:
    from .celery import app as celery_app
    __all__ = ('celery_app',)
except ImportError:
    __all__ = ()
