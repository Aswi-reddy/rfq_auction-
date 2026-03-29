"""
Extension Service - Auction extension trigger logic
"""
from django.utils import timezone
from datetime import timedelta


class ExtensionService:
    """Handles auction extension triggers and logic"""
    
    @staticmethod
    def should_extend_auction(auction, old_l1, new_l1, old_rankings):
        """
        Check if we should extend the auction.
        
        Returns: (should_extend: bool, reason: str)
        """
        now = timezone.now()
        config = auction.config
        
        if not config:
            return False, "No config defined"
        
        # Check if we're in trigger window
        trigger_window_seconds = config.trigger_window_x * 60
        trigger_start = auction.get_effective_close_time() - timedelta(seconds=trigger_window_seconds)
        
        if now < trigger_start or now > auction.get_effective_close_time():
            return False, "Outside trigger window"
        
        # Check if would exceed forced close
        potential_close = auction.get_effective_close_time() + timedelta(minutes=config.extension_duration_y)
        if potential_close > auction.forced_close_time:
            return False, "Would exceed forced close time"
        
        # Check trigger type
        if config.trigger_type == 'BID_RECEIVED':
            return True, f"BID_RECEIVED in trigger window (last {config.trigger_window_x} min)"
        
        elif config.trigger_type == 'RANK_CHANGE':
            # Check if any ranking changed (compare bidder IDs at each position)
            new_rankings = auction.get_all_bids_ranked()
            if len(old_rankings) != len(new_rankings):
                return True, "Supplier ranking changed"
            
            for old_bid, new_bid in zip(old_rankings, new_rankings):
                if old_bid.bidder_id != new_bid.bidder_id:
                    return True, "Supplier ranking changed"
            
            return False, "No ranking change"
        
        elif config.trigger_type == 'L1_CHANGE':
            if old_l1 is None or new_l1 is None:
                return False, "First bid - no L1 change"
            
            if old_l1.bidder_id != new_l1.bidder_id:
                return True, f"L1 changed: {old_l1.bidder.username} → {new_l1.bidder.username}"
            
            return False, "L1 unchanged"
        
        return False, "Unknown trigger type"
    
    @staticmethod
    def extend_auction(auction, reason):
        """
        Extend auction, capped at forced_close_time.
        
        Returns: (success: bool, new_close_time: datetime, was_capped: bool)
        """
        config = auction.config
        if not config:
            return False, auction.get_effective_close_time(), False
        
        current_close = auction.get_effective_close_time()
        new_close = current_close + timedelta(minutes=config.extension_duration_y)
        was_capped = False
        
        # Cap at forced close time
        if new_close > auction.forced_close_time:
            new_close = auction.forced_close_time
            was_capped = True
        
        # Save extension
        if new_close > current_close:
            auction.current_close_time = new_close
            auction.total_extensions += 1
            auction.save(update_fields=['current_close_time', 'total_extensions', 'updated_at'])
            return True, new_close, was_capped
        
        return False, current_close, was_capped
