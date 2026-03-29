import sys
import os
from pathlib import Path

# Add project to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rfq_auction.settings')

import django
django.setup()

from rfq_auction.wsgi import application

# Export for Vercel
app = application


