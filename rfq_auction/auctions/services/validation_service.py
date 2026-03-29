"""
Validation Service - All bid and auction validation logic
"""
from django.utils import timezone
from decimal import Decimal


class ValidationService:
    """Centralized validation for auctions and bids"""
    
    @staticmethod
    def validate_auction_open(auction):
        """Check if auction is still accepting bids"""
        now = timezone.now()
        
        if auction.status in ('CLOSED', 'FORCE_CLOSED'):
            raise ValueError(f"Auction is {auction.get_status_display()}, cannot accept bids")
        
        if now >= auction.forced_close_time:
            raise ValueError("Auction forced closed - no more bids accepted")
        
        if now < auction.bid_start_time:
            raise ValueError("Bidding hasn't started yet")
        
        if now > auction.get_effective_close_time():
            raise ValueError("Bidding has closed")
        
        return True
    
    @staticmethod
    def validate_bid_amount(price, freight=0, origin=0, destination=0):
        """Validate bid amounts"""
        try:
            price_d = Decimal(str(price))
            freight_d = Decimal(str(freight))
            origin_d = Decimal(str(origin))
            destination_d = Decimal(str(destination))
        except:
            raise ValueError("All prices must be valid numbers")
        
        if price_d < 0:
            raise ValueError("Base price cannot be negative")
        if freight_d < 0:
            raise ValueError("Freight charges cannot be negative")
        if origin_d < 0:
            raise ValueError("Origin charges cannot be negative")
        if destination_d < 0:
            raise ValueError("Destination charges cannot be negative")
        
        total = price_d + freight_d + origin_d + destination_d
        if total <= 0:
            raise ValueError("Total bid cost must be greater than zero")
        
        return price_d, freight_d, origin_d, destination_d
    
    @staticmethod
    def validate_bid_competitive(auction, bidder, new_total_cost):
        """Check if bid is competitive (must be lower than current L1)"""
        current_l1 = auction.get_best_bid()
        
        bidder_current_bid = (
            auction.bids
            .filter(bidder=bidder)
            .order_by('-submitted_at')
            .first()
        )
        
        # If bidder already has a bid, new bid must be lower (revision)
        if bidder_current_bid is not None:
            if new_total_cost >= bidder_current_bid.total_cost:
                raise ValueError(
                    f"Your revision must be lower than ₹{bidder_current_bid.total_cost}. "
                    f"You proposed ₹{new_total_cost}."
                )
        # If this is a new bid, must be lower than current L1
        else:
            if current_l1 is not None:
                if new_total_cost >= current_l1.total_cost:
                    raise ValueError(
                        f"Current lowest bid is ₹{current_l1.total_cost}. "
                        f"Your bid must be lower. You proposed ₹{new_total_cost}."
                    )
        
        return True
