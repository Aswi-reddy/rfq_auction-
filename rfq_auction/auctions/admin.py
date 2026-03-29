from django.contrib import admin
from auctions.models import Auction, Bid, AuctionConfig, AuctionEvent

@admin.register(AuctionConfig)
class AuctionConfigAdmin(admin.ModelAdmin):
    list_display = ['trigger_window_x', 'extension_duration_y', 'trigger_type']

@admin.register(Auction)
class AuctionAdmin(admin.ModelAdmin):
    list_display = ['name', 'status', 'bid_close_time', 'forced_close_time', 'total_extensions']
    list_filter = ['status']
    search_fields = ['name']

@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ['auction', 'bidder', 'price', 'total_cost', 'submitted_at']
    list_filter = ['auction', 'submitted_at']
    search_fields = ['bidder__username', 'auction__name']

@admin.register(AuctionEvent)
class AuctionEventAdmin(admin.ModelAdmin):
    list_display = ['auction', 'event_type', 'created_at']
    list_filter = ['event_type', 'created_at']
    search_fields = ['auction__name', 'description']
    readonly_fields = ['created_at']
