"""
Ranking Service - O(n) efficient ranking calculation
"""
from django.db.models import OuterRef, Subquery


class RankingService:
    """Efficient ranking calculation for auctions"""
    
    @staticmethod
    def get_latest_bids_per_bidder(auction):
        """Get latest bid from each bidder - O(n) efficient"""
        return auction.get_all_bids_ranked()
    
    @staticmethod
    def get_rankings(auction):
        """Get ranked list of bids (L1, L2, L3, ...)"""
        return auction.get_all_bids_ranked()
    
    @staticmethod
    def get_rank_for_bid(auction, bid):
        """Get rank for a specific bid"""
        rankings = RankingService.get_rankings(auction)
        for i, ranked_bid in enumerate(rankings, 1):
            if ranked_bid.id == bid.id:
                return i
        return None
