"""
Serializers for Auction API.
Clean data contracts for REST endpoints.
"""
from rest_framework import serializers
from auctions.models import Auction, Bid, AuctionEvent, AuctionConfig, AuctionSnapshot
from django.contrib.auth.models import User


class BidderSerializer(serializers.ModelSerializer):
    """Simple bidder/user info."""
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']


class AuctionConfigSerializer(serializers.ModelSerializer):
    """Auction configuration."""
    trigger_type_display = serializers.CharField(source='get_trigger_type_display', read_only=True)
    
    class Meta:
        model = AuctionConfig
        fields = [
            'id', 'trigger_window_x', 'extension_duration_y', 
            'trigger_type', 'trigger_type_display', 'created_at'
        ]


class BidSerializer(serializers.ModelSerializer):
    """Single bid details with calculated rank."""
    bidder_name = serializers.CharField(source='bidder.username', read_only=True)
    rank = serializers.SerializerMethodField()
    is_l1 = serializers.SerializerMethodField()
    
    class Meta:
        model = Bid
        fields = [
            'id', 'bidder_name', 'carrier_name', 'price', 'freight_charges',
            'origin_charges', 'destination_charges', 'total_cost',
            'transit_time_days', 'quote_validity_days', 'submitted_at',
            'rank', 'is_l1'
        ]
        read_only_fields = ['id', 'submitted_at', 'rank', 'is_l1']
    
    def get_rank(self, obj):
        """Get bid's rank in auction (1=best)"""
        try:
            return obj.get_rank()
        except:
            return None
    
    def get_is_l1(self, obj):
        """Check if this bid is L1"""
        try:
            return obj.is_l1()
        except:
            return False


class AuctionEventSerializer(serializers.ModelSerializer):
    """Activity log event."""
    event_type_display = serializers.CharField(source='get_event_type_display', read_only=True)
    bidder_name = serializers.CharField(source='bidder.username', read_only=True, allow_null=True)
    
    class Meta:
        model = AuctionEvent
        fields = [
            'id', 'event_type', 'event_type_display', 'created_at',
            'description', 'extension_reason', 'bidder_name'
        ]
        read_only_fields = fields


class AuctionListSerializer(serializers.ModelSerializer):
    """Auction listing page - summary view."""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    best_bid_amount = serializers.SerializerMethodField()
    best_bidder_name = serializers.SerializerMethodField()
    total_bidders = serializers.SerializerMethodField()
    time_until_close = serializers.SerializerMethodField()
    
    class Meta:
        model = Auction
        fields = [
            'id', 'name', 'status', 'status_display',
            'bid_close_time', 'forced_close_time', 'current_close_time',
            'best_bid_amount', 'best_bidder_name', 'total_bidders',
            'time_until_close', 'total_extensions', 'created_at'
        ]
        read_only_fields = fields
    
    def get_best_bid_amount(self, obj):
        try:
            l1 = obj.get_best_bid()
            return float(l1.total_cost) if l1 else None
        except:
            return None
    
    def get_best_bidder_name(self, obj):
        try:
            l1 = obj.get_best_bid()
            return l1.bidder.username if l1 else None
        except:
            return None
    
    def get_total_bidders(self, obj):
        return obj.bids.values('bidder').distinct().count()
    
    def get_time_until_close(self, obj):
        from django.utils import timezone
        now = timezone.now()
        close_time = obj.get_effective_close_time()
        if close_time > now:
            return int((close_time - now).total_seconds())
        return 0


class AuctionDetailSerializer(serializers.ModelSerializer):
    """Detailed auction view with all data."""
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    config = AuctionConfigSerializer(read_only=True)
    created_by_name = serializers.CharField(source='created_by.username', read_only=True)
    
    # Rankings  
    rankings = serializers.SerializerMethodField()
    
    # Recent activity
    recent_events = serializers.SerializerMethodField()
    
    class Meta:
        model = Auction
        fields = [
            'id', 'name', 'description', 'status', 'status_display',
            'bid_start_time', 'bid_close_time', 'forced_close_time', 'current_close_time',
            'created_by', 'created_by_name', 'config',
            'total_bids', 'total_extensions',
            'rankings', 'recent_events', 'created_at', 'updated_at'
        ]
        read_only_fields = fields
    
    def get_rankings(self, obj):
        """Get ranked bids with details"""
        try:
            from auctions.services.auction_engine import AuctionEngineService
            return AuctionEngineService.get_rankings(obj)
        except:
            return []
    
    def get_recent_events(self, obj):
        """Get last 20 events"""
        events = obj.events.order_by('-created_at')[:20]
        return AuctionEventSerializer(events, many=True).data
    
    @property
    def total_bids(self):
        return self.instance.bids.count()


class PlaceBidSerializer(serializers.Serializer):
    """Input serializer for placing a bid."""
    price = serializers.DecimalField(max_digits=12, decimal_places=2)
    freight_charges = serializers.DecimalField(max_digits=10, decimal_places=2, default=0)
    origin_charges = serializers.DecimalField(max_digits=10, decimal_places=2, default=0)
    destination_charges = serializers.DecimalField(max_digits=10, decimal_places=2, default=0)
    transit_time_days = serializers.IntegerField(default=1, min_value=1)
    quote_validity_days = serializers.IntegerField(default=30, min_value=1)
    carrier_name = serializers.CharField(max_length=255, default='Unknown')


class CreateAuctionSerializer(serializers.ModelSerializer):
    """Input serializer for creating auction."""
    config_id = serializers.IntegerField(required=False, allow_null=True)
    
    class Meta:
        model = Auction
        fields = [
            'name', 'description', 'bid_start_time',
            'bid_close_time', 'forced_close_time', 'config_id'
        ]
    
    def create(self, validated_data):
        config_id = validated_data.pop('config_id', None)
        auction = Auction.objects.create(
            created_by=self.context['request'].user,
            **validated_data
        )
        if config_id:
            auction.config_id = config_id
            auction.save(update_fields=['config'])
        return auction


class AuctionListSerializer(serializers.ModelSerializer):
    """Auction listing - simple."""
    
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = Auction
        fields = [
            'id', 'name', 'status', 'status_display', 'bid_start_time', 
            'bid_close_time', 'current_close_time', 'forced_close_time',
            'total_extensions'
        ]


class AuctionDetailSerializer(serializers.ModelSerializer):
    """Auction details with rankings and events."""
    
    config = AuctionConfigSerializer(read_only=True)
    
    class Meta:
        model = Auction
        fields = [
            'id', 'name', 'description', 'status', 'bid_start_time',
            'bid_close_time', 'current_close_time', 'forced_close_time',
            'total_extensions', 'config'
        ]


class CreateAuctionSerializer(serializers.ModelSerializer):
    """For creating auctions via API."""
    
    trigger_window_x = serializers.IntegerField(write_only=True, required=False, default=10)
    extension_duration_y = serializers.IntegerField(write_only=True, required=False, default=5)
    trigger_type = serializers.ChoiceField(
        choices=['BID_RECEIVED', 'RANK_CHANGE', 'L1_CHANGE'],
        write_only=True, 
        required=False, 
        default='BID_RECEIVED'
    )
    
    class Meta:
        model = Auction
        fields = [
            'name', 'description', 'bid_start_time', 'bid_close_time',
            'forced_close_time', 'trigger_window_x', 'extension_duration_y', 
            'trigger_type'
        ]
    
    def create(self, validated_data):
        trigger_window_x = validated_data.pop('trigger_window_x', 10)
        extension_duration_y = validated_data.pop('extension_duration_y', 5)
        trigger_type = validated_data.pop('trigger_type', 'BID_RECEIVED')
        
        config = AuctionConfig.objects.create(
            trigger_window_x=trigger_window_x,
            extension_duration_y=extension_duration_y,
            trigger_type=trigger_type
        )
        
        auction = Auction.objects.create(config=config, **validated_data)
        AuctionEvent.objects.create(
            auction=auction,
            event_type='AUCTION_CREATED',
            description=f'Auction created: {auction.name}'
        )
        return auction


class PlaceBidSerializer(serializers.Serializer):
    """For bidder to place bid via API."""
    
    carrier_name = serializers.CharField(max_length=255, required=True)
    price = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)
    freight_charges = serializers.DecimalField(max_digits=12, decimal_places=2, default=0, required=False)
    origin_charges = serializers.DecimalField(max_digits=12, decimal_places=2, default=0, required=False)
    destination_charges = serializers.DecimalField(max_digits=12, decimal_places=2, default=0, required=False)
    transit_time_days = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    quote_validity_days = serializers.IntegerField(required=False, default=30, min_value=1)
    
    def validate_price(self, value):
        if value <= 0:
            raise serializers.ValidationError("Price must be greater than 0")
        return value
    
    def validate_carrier_name(self, value):
        if not value or len(value.strip()) == 0:
            raise serializers.ValidationError("Carrier name cannot be empty")
        return value.strip()
