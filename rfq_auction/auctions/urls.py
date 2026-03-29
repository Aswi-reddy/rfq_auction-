"""
URL Configuration for RFQ British Auction System
=================================================

URL Structure (RESTful, role-based namespacing):

    /                                 -> Landing page (role selection)
    /auth/logout/                     -> Logout (shared)

    /auctioneer/
        register/                     -> Auctioneer registration
        login/                        -> Auctioneer login
        dashboard/                    -> Auctioneer dashboard
        auctions/create/              -> Create new auction
        auctions/<id>/                -> Auction detail (live view)
        auctions/<id>/live-data/      -> JSON API for live polling

    /bidder/
        register/                     -> Bidder registration
        login/                        -> Bidder login
        dashboard/                    -> Bidder dashboard
        auctions/<id>/                -> Auction detail (bidder view)
        auctions/<id>/bid/            -> Place/revise bid
        auctions/<id>/live-data/      -> JSON API for live polling

    /admin/                           -> Django admin panel
"""

from django.urls import path
from auctions import views

urlpatterns = [
    # LANDING
    path('', views.landing, name='landing'),

    # AUTH
    path('auth/logout/', views.logout_view, name='logout'),

    # AUCTIONEER ROUTES
    path('auctioneer/register/', views.auctioneer_register, name='auctioneer_register'),
    path('auctioneer/login/', views.auctioneer_login, name='auctioneer_login'),
    path('auctioneer/dashboard/', views.auctioneer_dashboard, name='auctioneer_dashboard'),
    path('auctioneer/auctions/create/', views.create_auction, name='create_auction'),
    path('auctioneer/auctions/<int:auction_id>/', views.auction_detail, name='auction_detail'),
    path('auctioneer/auctions/<int:auction_id>/live-data/', views.auction_live_data, name='auction_live_data'),

    # BIDDER ROUTES
    path('bidder/register/', views.bidder_register, name='bidder_register'),
    path('bidder/login/', views.bidder_login, name='bidder_login'),
    path('bidder/dashboard/', views.bidder_dashboard, name='bidder_dashboard'),
    path('bidder/auctions/<int:auction_id>/', views.bidder_auction_detail, name='bidder_auction_detail'),
    path('bidder/auctions/<int:auction_id>/bid/', views.place_bid, name='place_bid'),
    path('bidder/auctions/<int:auction_id>/live-data/', views.auction_live_data, name='bidder_auction_live_data'),
]
