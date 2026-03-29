"""
URL configuration for rfq_auction project.
Main routing for REST API and HTML views.
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from auctions import api_views

# REST API Router - DRF ViewSet routing
router = DefaultRouter()
router.register(r'auctions', api_views.AuctionViewSet, basename='auction')
router.register(r'bids', api_views.BidViewSet, basename='bid')
router.register(r'configs', api_views.AuctionConfigViewSet, basename='config')

urlpatterns = [
    # Django Admin
    path('admin/', admin.site.urls),
    
    # REST API endpoints (DRF)
    # /api/auctions/    - auction list, create
    # /api/auctions/ID/ - auction detail
    # /api/bids/        - bid list, create
    # /api/configs/     - config list
    path('api/', include(router.urls)),
    
    # HTML form-based views (traditional Django)
    # /                        - landing
    # /auctioneer/dashboard/   - etc
    # /bidder/dashboard/       - etc
    path('', include('auctions.urls')),
]
