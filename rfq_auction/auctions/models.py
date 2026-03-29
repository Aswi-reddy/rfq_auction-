from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from django.core.exceptions import ValidationError
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)


# ========== AUCTION CONFIG ==========
class AuctionConfig(models.Model):
    """Configuration for auction behavior (X and Y values per British Auction specification)"""
    
    TRIGGER_CHOICES = [
        ('BID_RECEIVED', 'Bid Received in Last X Minutes'),
        ('RANK_CHANGE', 'Any Supplier Rank Change in Last X Minutes'),
        ('L1_CHANGE', 'Lowest Bidder (L1) Rank Change'),
    ]
    
    trigger_window_x = models.PositiveIntegerField(
        default=10,
        help_text="Trigger Window X: Minutes before close to monitor for bidding activity"
    )
    extension_duration_y = models.PositiveIntegerField(
        default=5,
        help_text="Extension Duration Y: Minutes to extend auction when triggered"
    )
    trigger_type = models.CharField(
        max_length=20, 
        choices=TRIGGER_CHOICES, 
        default='BID_RECEIVED',
        help_text="Type of activity that triggers extension"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "Auction Configs"
    
    def __str__(self):
        return f"Config: X={self.trigger_window_x}min, Y={self.extension_duration_y}min, Type={self.get_trigger_type_display()}"


# ========== AUCTION ==========
class Auction(models.Model):
    """RFQ with British Auction - automatic extension support"""
    
    STATUS_CHOICES = [
        ('SCHEDULED', 'Scheduled - Not Yet Started'),
        ('ACTIVE', 'Active - Bidding Open'),
        ('CLOSED', 'Closed - Bidding Ended'),
        ('FORCE_CLOSED', 'Force Closed - Hard Deadline Reached'),
    ]
    
    # Auctioneer who created this RFQ
    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='auctions_created', null=True, blank=True
    )
    
    # RFQ Details
    name = models.CharField(max_length=255, help_text="RFQ Name / Reference ID")
    description = models.TextField(blank=True, help_text="RFQ Description")
    
    # Auction Timing (per British Auction spec)
    bid_start_time = models.DateTimeField(
        help_text="Bid Start Date & Time (Asia/Kolkata timezone - IST, UTC+5:30)"
    )
    bid_close_time = models.DateTimeField(
        help_text="Bid Close Date & Time (Asia/Kolkata timezone - IST, UTC+5:30)"
    )
    forced_close_time = models.DateTimeField(
        help_text="Forced Bid Close Date & Time (must be > Bid Close Time) - IST timezone"
    )
    current_close_time = models.DateTimeField(
        null=True, blank=True,
        help_text="Current effective close time (with extensions) - IST timezone"
    )
    
    # Configuration
    config = models.ForeignKey(
        AuctionConfig, on_delete=models.SET_NULL,
        null=True, related_name='auctions'
    )
    
    # Status & Tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SCHEDULED')
    total_extensions = models.PositiveIntegerField(
        default=0, help_text="Total number of times auction was extended"
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Auctions"
        indexes = [
            models.Index(fields=['status', 'bid_start_time']),
            models.Index(fields=['status', 'current_close_time']),
            models.Index(fields=['status', 'forced_close_time']),
            models.Index(fields=['created_by', 'status']),
            models.Index(fields=['bid_close_time']),
            models.Index(fields=['forced_close_time']),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"
    
    def clean(self):
        """
        🔍 Validate auction timing constraints.
        Called by: model.full_clean() or form.save() + full_clean()
        """
        errors = {}
        
        # Validation 1: bid_start < bid_close
        if self.bid_start_time and self.bid_close_time:
            if self.bid_start_time >= self.bid_close_time:
                errors['bid_close_time'] = (
                    "Bid close time must be AFTER bid start time"
                )
        
        # Validation 2: bid_close < forced_close (CRITICAL!)
        if self.bid_close_time and self.forced_close_time:
            if self.bid_close_time >= self.forced_close_time:
                errors['forced_close_time'] = (
                    "Forced close time must be AFTER bid close time"
                )
            
            # Validation 3: Minimum buffer required
            min_buffer = timedelta(minutes=5)
            gap = self.forced_close_time - self.bid_close_time
            if gap < min_buffer:
                errors['forced_close_time'] = (
                    f"Buffer required: at least 5 minutes. Got {gap.total_seconds() / 60:.1f} min"
                )
        
        if errors:
            raise ValidationError(errors)
    
    def save(self, *args, **kwargs):
        """Run validations before saving"""
        self.full_clean()
        super().save(*args, **kwargs)
    
    def get_effective_close_time(self):
        """Returns the actual close time (with extensions if any)"""
        return self.current_close_time or self.bid_close_time
    
    def is_active(self):
        """Check if auction is open for bidding"""
        now = timezone.now()
        return (
            self.status == 'ACTIVE'
            and now >= self.bid_start_time
            and now <= self.get_effective_close_time()
        )
    
    def is_in_trigger_window(self):
        """
        Check if current time is within trigger window.
        
        The trigger window is the last X minutes before the current close time.
        Example: close_time=6:00PM, X=10 → window is 5:50PM–6:00PM
        """
        if not self.config:
            return False
        
        # Must be active for trigger window to matter
        if self.status != 'ACTIVE':
            return False
        
        now = timezone.now()
        close_time = self.get_effective_close_time()
        trigger_start = close_time - timedelta(minutes=self.config.trigger_window_x)
        
        return trigger_start <= now <= close_time
    
    def can_extend(self):
        """
        Check if auction can be extended (not at forced close).
        Extension must NEVER exceed forced_close_time.
        """
        close_time = self.get_effective_close_time()
        return close_time < self.forced_close_time
    
    @transaction.atomic
    def update_status(self):
        """
        🔒 Auto-update auction status with row-level locking.
        ATOMIC: Prevents race conditions in concurrent bid scenarios.
        
        Priority order (checked in sequence):
        1. now >= forced_close_time → FORCE_CLOSED
        2. now >= effective_close_time → CLOSED
        3. now >= bid_start_time → ACTIVE
        4. else → SCHEDULED
        """
        now = timezone.now()
        
        # Re-fetch with exclusive lock to prevent concurrent updates
        auction_locked = Auction.objects.select_for_update().get(id=self.id)
        new_status = auction_locked.status
        
        # Determine new status (order matters!)
        if now >= auction_locked.forced_close_time:
            new_status = 'FORCE_CLOSED'
        elif now >= auction_locked.get_effective_close_time():
            new_status = 'CLOSED'
        elif now >= auction_locked.bid_start_time:
            new_status = 'ACTIVE'
        else:
            new_status = 'SCHEDULED'
        
        # Only update if status actually changed
        if new_status != auction_locked.status:
            auction_locked.status = new_status
            auction_locked.save(update_fields=['status', 'updated_at'])
            logger.info(f'✓ Auction {auction_locked.id} status: {auction_locked.status} → {new_status}')
            
            # Update self for consistency
            self.status = new_status
            self.updated_at = auction_locked.updated_at
    
    def _get_latest_bids_per_bidder(self):
        """
        ⚡ Get the LATEST bid from each bidder using optimized Django ORM.
        Uses Subquery for SQLite/PostgreSQL compatibility.
        O(n) database query, lightning fast ranking.
        
        Returns: list of Bid objects (one per bidder, the latest one)
        """
        from django.db.models import Max, OuterRef, Subquery
        
        # Subquery: Get the latest submitted_at for each bidder
        latest_submitted = Bid.objects.filter(
            auction=self,
            bidder=OuterRef('bidder')
        ).order_by('-submitted_at').values('id')[:1]
        
        # Main query: Get bids using the subquery
        latest_bids = Bid.objects.filter(
            auction=self,
            id__in=Subquery(latest_submitted)
        ).select_related('bidder')
        
        return list(latest_bids.order_by('-submitted_at'))
    
    def _get_latest_bids_per_bidder_orm(self):
        """
        ✨ OPTIONAL: Get latest bid per bidder using pure Django ORM.
        
        This is an alternative to the raw SQL version.
        Use this for better database portability (MySQL, SQLite, Oracle).
        
        Performance: Same O(1) complexity, slightly slower than raw SQL.
        Storage: More readable, easier to maintain.
        
        Replaces: _get_latest_bids_per_bidder for improved compatibility
        """
        from django.db.models import OuterRef, Subquery
        
        # Subquery: For each bidder, find the bid with latest timestamp
        latest_bid_subquery = (
            Bid.objects
            .filter(
                auction=self,
                bidder=OuterRef('bidder')
            )
            .order_by('-submitted_at')
            .values('id')[:1]
        )
        
        # Main query: Get those specific bid IDs
        return list(
            Bid.objects
            .filter(
                auction=self,
                id__in=Subquery(latest_bid_subquery)
            )
            .select_related('bidder')
            .order_by('-submitted_at')
        )
    
    def get_best_bid(self):
        """
        Get the lowest-cost bid (L1) considering only latest bid per supplier.
        """
        latest_bids = self._get_latest_bids_per_bidder()
        if not latest_bids:
            return None
        return min(latest_bids, key=lambda b: b.total_cost)
    
    def get_all_bids_ranked(self):
        """
        Get ranked bids (L1, L2, L3, ...) cached for 5 seconds.
        Uses LATEST bid per bidder, sorted by total_cost ascending.
        """
        cache_key = f'auction_{self.id}_rankings'
        rankings = cache.get(cache_key)
        
        if rankings is None:
            # Cache miss: fetch and sort
            latest_bids = self._get_latest_bids_per_bidder()
            rankings = sorted(latest_bids, key=lambda b: (b.total_cost, b.submitted_at))
            cache.set(cache_key, rankings, timeout=5)  # 5 second TTL
        
        return rankings
    
    def invalidate_rankings_cache(self):
        """Clear rankings cache after bid placed or auction closed."""
        cache_key = f'auction_{self.id}_rankings'
        cache.delete(cache_key)
    
    def get_bid_rank(self, bid):
        """Get rank of a specific bid (1 = lowest = best)"""
        ranked = self.get_all_bids_ranked()
        for idx, b in enumerate(ranked, 1):
            if b.bidder_id == bid.bidder_id:
                return idx
        return None


# ========== BIDS ==========
class Bid(models.Model):
    """
    Supplier bid on an auction - Quote submission for RFQ.
    
    A supplier CAN place multiple bids (revisions). Only the LATEST bid
    from each supplier is considered for ranking.
    """
    
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='bids')
    bidder = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bids')
    
    # Carrier Details
    carrier_name = models.CharField(
        max_length=255, default='', blank=True,
        help_text="Name of the logistics carrier providing the service"
    )
    
    # Quote Details (per British Auction spec)
    price = models.DecimalField(max_digits=12, decimal_places=2, help_text="Base price for quote")
    freight_charges = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, help_text="Freight charges"
    )
    origin_charges = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, help_text="Origin/Pickup charges"
    )
    destination_charges = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, help_text="Destination/Delivery charges"
    )
    
    # Logistics Details
    transit_time_days = models.PositiveIntegerField(help_text="Transit time in days")
    quote_validity_days = models.PositiveIntegerField(help_text="Quote validity period in days")
    
    # Tracking
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-submitted_at']
        verbose_name_plural = "Bids"
        # NO unique_together - suppliers CAN revise bids multiple times
        # This preserves complete audit trail of bid changes
        indexes = [
            # Query latest bid per supplier efficiently
            models.Index(fields=['auction', 'bidder', '-submitted_at']),
            # Find bids in trigger window
            models.Index(fields=['auction', 'submitted_at']),
            # Ranking and L1 queries
            models.Index(fields=['auction', '-submitted_at']),
        ]
    
    def __str__(self):
        return f"{self.bidder.username} - {self.auction.name} - ₹{self.total_cost}"
    
    @property
    def total_cost(self):
        """Calculate total landed cost = Base + Freight + Origin + Destination"""
        return self.price + self.freight_charges + self.origin_charges + self.destination_charges
    
    def get_rank(self):
        """Get this bid's rank in the auction (1 = best/lowest)"""
        return self.auction.get_bid_rank(self)
    
    def is_l1(self):
        """Check if this bidder is currently the lowest bidder (L1)"""
        return self.get_rank() == 1


# ========== ACTIVITY LOG ==========
class AuctionEvent(models.Model):
    """Activity log for auction - Complete audit trail per British Auction spec"""
    
    EVENT_CHOICES = [
        ('AUCTION_CREATED', 'Auction Created'),
        ('BID_RECEIVED', 'Bid Received'),
        ('BID_REVISED', 'Bid Revised'),
        ('RANK_CHANGED', 'Rank Changed'),
        ('L1_CHANGED', 'L1 (Lowest Bidder) Changed'),
        ('EXTENDED', 'Auction Extended'),
        ('CLOSED', 'Auction Closed'),
        ('FORCE_CLOSED', 'Force Closed'),
    ]
    
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='events')
    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES, help_text="Type of event")
    description = models.TextField(help_text="Detailed event description")
    bidder = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='events', help_text="Bidder involved (if applicable)"
    )
    
    # Reason for extension (if applicable)
    extension_reason = models.CharField(max_length=255, blank=True, help_text="Reason for extension trigger")
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        verbose_name_plural = "Auction Events"
    
    def __str__(self):
        return f"{self.auction.name} - {self.get_event_type_display()} at {self.created_at.strftime('%H:%M:%S')}"


# ========== AUDIT SNAPSHOTS ==========
class AuctionSnapshot(models.Model):
    """
    📸 Snapshot of auction state at key moments.
    For post-auction analysis, fairness audits, and performance analytics.
    """
    auction = models.ForeignKey(Auction, on_delete=models.CASCADE, related_name='snapshots')
    
    # State at this exact moment
    auction_status = models.CharField(max_length=20, choices=Auction.STATUS_CHOICES)
    current_close_time = models.DateTimeField()
    l1_bidder = models.CharField(max_length=150, blank=True)
    l1_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_bids = models.PositiveIntegerField()
    unique_bidders = models.PositiveIntegerField()
    total_extensions = models.PositiveIntegerField()
    
    # What triggered this snapshot
    trigger_event = models.CharField(
        max_length=50,
        choices=[
            ('BID_PLACED', 'Bid Placed'),
            ('EXTENSION', 'Auction Extended'),
            ('CLOSED', 'Auction Closed'),
            ('L1_CHANGE', 'L1 Changed'),
        ]
    )
    trigger_description = models.TextField()
    
    snapshot_time = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-snapshot_time']
        verbose_name_plural = "Auction Snapshots"
        indexes = [
            models.Index(fields=['auction', '-snapshot_time']),
        ]
    
    def __str__(self):
        return f"{self.auction.name} snapshot @ {self.snapshot_time.strftime('%H:%M:%S')}"
    
    @staticmethod
    def take_snapshot(auction, trigger_event, trigger_description):
        """Create snapshot at current moment"""
        best_bid = auction.get_best_bid()
        ranked_bids = auction.get_all_bids_ranked()
        
        return AuctionSnapshot.objects.create(
            auction=auction,
            auction_status=auction.status,
            current_close_time=auction.get_effective_close_time(),
            l1_bidder=best_bid.bidder.username if best_bid else '',
            l1_price=best_bid.total_cost if best_bid else 0,
            total_bids=auction.bids.count(),
            unique_bidders=len(ranked_bids),
            total_extensions=auction.total_extensions,
            trigger_event=trigger_event,
            trigger_description=trigger_description,
        )


# ========== AUCTION STATISTICS ==========
class AuctionStatistics(models.Model):
    """
    📊 Analytics calculated at auction end.
    Shows performance metrics and competitive metrics.
    """
    auction = models.OneToOneField(Auction, on_delete=models.CASCADE, related_name='statistics')
    
    # Participation metrics
    total_bids_received = models.PositiveIntegerField()
    unique_bidders = models.PositiveIntegerField()
    avg_bids_per_bidder = models.FloatField()
    
    # Price metrics
    initial_bid_price = models.DecimalField(max_digits=12, decimal_places=2)
    final_bid_price = models.DecimalField(max_digits=12, decimal_places=2)
    price_reduction = models.DecimalField(max_digits=12, decimal_places=2)
    price_reduction_percent = models.FloatField()
    
    # Time metrics
    total_auction_duration = models.DurationField()
    total_extension_time = models.DurationField()
    first_bid_to_close_time = models.DurationField()
    
    # Extension metrics
    total_extensions = models.PositiveIntegerField()
    
    # Bidding activity
    bid_density = models.FloatField()  # bids per minute
    final_l1_bidder = models.CharField(max_length=150, blank=True)
    
    calculated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name_plural = "Auction Statistics"
    
    def __str__(self):
        return f"{self.auction.name} - {self.price_reduction_percent:.1f}% reduction"
    
    @staticmethod
    def calculate_and_store(auction):
        """Calculate and store statistics for completed auction"""
        best_bid = auction.get_best_bid()
        all_bids = auction.bids.all()
        ranked_bids = auction.get_all_bids_ranked()
        
        first_bid = all_bids.order_by('submitted_at').first()
        
        total_auction_duration = auction.get_effective_close_time() - auction.bid_start_time
        total_extension_time = (auction.current_close_time or auction.bid_close_time) - auction.bid_close_time
        first_bid_to_close = auction.get_effective_close_time() - (first_bid.submitted_at if first_bid else auction.bid_start_time)
        
        initial_price = first_bid.total_cost if first_bid else 0
        final_price = best_bid.total_cost if best_bid else 0
        price_reduction = initial_price - final_price
        price_reduction_pct = (price_reduction / initial_price * 100) if initial_price > 0 else 0
        
        bid_count = all_bids.count()
        bidder_count = len(ranked_bids) if ranked_bids else 1
        duration_minutes = total_auction_duration.total_seconds() / 60 if total_auction_duration.total_seconds() > 0 else 1
        bid_density = bid_count / duration_minutes
        
        stats, created = AuctionStatistics.objects.update_or_create(
            auction=auction,
            defaults={
                'total_bids_received': bid_count,
                'unique_bidders': bidder_count,
                'avg_bids_per_bidder': bid_count / bidder_count if bidder_count > 0 else 0,
                'initial_bid_price': initial_price,
                'final_bid_price': final_price,
                'price_reduction': price_reduction,
                'price_reduction_percent': price_reduction_pct,
                'total_auction_duration': total_auction_duration,
                'total_extension_time': total_extension_time,
                'first_bid_to_close_time': first_bid_to_close,
                'total_extensions': auction.total_extensions,
                'bid_density': bid_density,
                'final_l1_bidder': best_bid.bidder.username if best_bid else '',
            }
        )
        
        return stats
