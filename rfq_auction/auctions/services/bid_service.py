"""
Bid Service - Clean bid placement API (thin wrapper around AuctionEngineService)
"""
from auctions.services.auction_engine import AuctionEngineService
import logging

logger = logging.getLogger(__name__)


class BidService:
    """
    Clean API for bid placement.
    
    This is a thin wrapper around AuctionEngineService for easier usage.
    All heavy lifting is done by the engine with atomic transactions,
    locking, and event logging.
    """
    
    @staticmethod
    def place_bid(auction, bidder, price, freight=0, origin=0, destination=0,
                  transit_days=1, validity_days=30, carrier_name="Unknown"):
        """
        Place a new bid or revise an existing one on an auction.
        
        This delegates to AuctionEngineService.process_bid which handles:
        - Atomic transaction with row-level locking
        - All validations (auction open, bid amounts, etc)
        - L1 change detection
        - Extension trigger checking
        - Complete event logging (audit trail)
        
        Args:
            auction: Auction model instance
            bidder: User model instance (the supplier)
            price: Base price (Decimal or numeric)
            freight, origin, destination: Component charges
            transit_days: Logistics transit time
            validity_days: How long quote is valid
            carrier_name: Name of logistics carrier
        
        Returns dict:
            {
                'success': bool - Whether bid was placed successfully
                'bid': Bid object or None
                'events': [AuctionEvent] - All events logged (bid, L1 change, extension, etc)
                'l1_changed': bool - Whether the L1 changed after this bid
                'extended': bool - Whether auction was extended
                'new_close_time': datetime - Updated close time (if extended)
                'total_extensions': int - Total extension count
                'is_revision': bool - Whether this was a revision or new bid
                'error': str or None - Error message if failed
            }
        """
        try:
            result = AuctionEngineService.process_bid(
                auction_id=auction.id,
                bidder=bidder,
                price=price,
                freight=freight,
                origin=origin,
                destination=destination,
                transit_days=transit_days,
                validity_days=validity_days,
                carrier_name=carrier_name,
            )
            
            if result['success']:
                logger.info(
                    f"✓ Bid placed: {bidder.username} on {auction.name} | "
                    f"Cost: Rs.{result['bid'].total_cost} | "
                    f"L1 Changed: {result['l1_changed']} | "
                    f"Extended: {result['extended']}"
                )
            else:
                logger.warning(
                    f"✗ Bid placement failed: {bidder.username} on {auction.name} | "
                    f"Error: {result['error']}"
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Unexpected error in place_bid: {str(e)}", exc_info=True)
            return {
                'success': False,
                'bid': None,
                'events': [],
                'error': f"System error: {str(e)}",
                'l1_changed': False,
                'extended': False,
                'new_close_time': None,
                'total_extensions': None,
                'is_revision': False,
            }
