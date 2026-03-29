"""
REST API Views for British Auction System.
Production-ready DRF viewsets with role-based access control.
"""

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from django.utils import timezone
from decimal import Decimal

from auctions.models import Auction, Bid, AuctionConfig, AuctionEvent
from auctions.serializers import (
    AuctionListSerializer, AuctionDetailSerializer,
    BidSerializer, AuctionEventSerializer, AuctionConfigSerializer,
    CreateAuctionSerializer, PlaceBidSerializer, BidderSerializer
)
from auctions.services.auction_engine import AuctionEngineService
from auctions.services.bid_service import BidService
import logging

logger = logging.getLogger(__name__)


# ============================================
# PERMISSIONS
# ============================================

class IsAuctioneer(permissions.BasePermission):
    """Only users in 'Auctioneer' group"""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.groups.filter(name='Auctioneer').exists()


class IsBidder(permissions.BasePermission):
    """Only users in 'Bidder' group"""
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.groups.filter(name='Bidder').exists()


# ============================================
# PAGINATION
# ============================================

class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


# ============================================
# VIEWSETS
# ============================================

class AuctionViewSet(viewsets.ModelViewSet):
    """Auction CRUD + custom actions"""
    
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    
    def get_queryset(self):
        """Auctioneers see only their auctions, bidders see all"""
        if self.request.user.groups.filter(name='Auctioneer').exists():
            return Auction.objects.filter(created_by=self.request.user).order_by('-created_at')
        return Auction.objects.all().order_by('-created_at')
    
    def get_serializer_class(self):
        """Use lighter serializer for list view"""
        if self.action == 'list':
            return AuctionListSerializer
        elif self.action == 'create':
            return CreateAuctionSerializer
        return AuctionDetailSerializer
    
    def create(self, request, *args, **kwargs):
        """Create auction - auctioneer only"""
        if not request.user.groups.filter(name='Auctioneer').exists():
            return Response(
                {'detail': 'Only auctioneers can create auctions'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        serializer = CreateAuctionSerializer(
            data=request.data,
            context={'request': request}
        )
        if serializer.is_valid():
            auction = serializer.save()
            return Response(
                AuctionDetailSerializer(auction).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'])
    def rankings(self, request, pk=None):
        """Get current L1, L2, L3 rankings"""
        auction = self.get_object()
        try:
            rankings = AuctionEngineService.get_rankings(auction)
            return Response({
                'auction_id': auction.id,
                'rankings': rankings,
                'total_bids': auction.bids.count(),
                'unique_bidders': auction.bids.values('bidder').distinct().count(),
            })
        except Exception as e:
            return Response(
                {'detail': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=True, methods=['get'])
    def events(self, request, pk=None):
        """Get activity log"""
        auction = self.get_object()
        events = auction.events.all().order_by('-created_at')[:50]
        serializer = AuctionEventSerializer(events, many=True)
        return Response({
            'auction_id': auction.id,
            'total_events': auction.events.count(),
            'events': serializer.data
        })
    
    @action(detail=True, methods=['get'])
    def bids_detail(self, request, pk=None):
        """Get all bids on this auction"""
        auction = self.get_object()
        bids = auction.bids.order_by('-submitted_at')
        serializer = BidSerializer(bids, many=True)
        return Response({
            'auction_id': auction.id,
            'auction_name': auction.name,
            'total_bids': bids.count(),
            'unique_bidders': bids.values('bidder').distinct().count(),
            'bids': serializer.data
        })


class BidViewSet(viewsets.ModelViewSet):
    """Bid placement and querying"""
    
    serializer_class = BidSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    
    def get_queryset(self):
        """Filter by auction_id if provided"""
        auction_id = self.request.query_params.get('auction_id')
        if auction_id:
            return Bid.objects.filter(auction_id=auction_id).order_by('-submitted_at')
        return Bid.objects.all().order_by('-submitted_at')
    
    def create(self, request, *args, **kwargs):
        """Place a bid on an auction - bidder only"""
        if not request.user.groups.filter(name='Bidder').exists():
            return Response(
                {'detail': 'Only bidders can place bids'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Parse input
        try:
            auction_id = int(request.data.get('auction_id'))
            auction = Auction.objects.get(id=auction_id)
        except (ValueError, Auction.DoesNotExist):
            return Response(
                {'detail': 'Invalid auction_id'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        serializer = PlaceBidSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Use AuctionEngineService for atomic bid placement
        result = AuctionEngineService.process_bid(
            auction_id=auction.id,
            bidder=request.user,
            price=serializer.validated_data['price'],
            freight=serializer.validated_data.get('freight_charges', 0),
            origin=serializer.validated_data.get('origin_charges', 0),
            destination=serializer.validated_data.get('destination_charges', 0),
            transit_days=serializer.validated_data.get('transit_time_days', 1),
            validity_days=serializer.validated_data.get('quote_validity_days', 30),
            carrier_name=serializer.validated_data.get('carrier_name', 'Unknown'),
        )
        
        if result['success']:
            bid = result['bid']
            return Response({
                'success': True,
                'bid': BidSerializer(bid).data,
                'l1_changed': result['l1_changed'],
                'extended': result['extended'],
                'new_close_time': result['new_close_time'].isoformat() if result['new_close_time'] else None,
                'total_extensions': result['total_extensions'],
                'is_revision': result['is_revision'],
                'events': AuctionEventSerializer(result['events'], many=True).data
            }, status=status.HTTP_201_CREATED)
        else:
            return Response(
                {'detail': result['error']},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['get'])
    def my_bids(self, request):
        """Get all bids placed by current user"""
        if not request.user.groups.filter(name='Bidder').exists():
            return Response(
                {'detail': 'Only bidders can view bids'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        bids = Bid.objects.filter(bidder=request.user).order_by('-submitted_at')
        page = self.paginate_queryset(bids)
        if page is not None:
            serializer = BidSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = BidSerializer(bids, many=True)
        return Response(serializer.data)


class AuctionConfigViewSet(viewsets.ReadOnlyModelViewSet):
    """View auction configurations - Read-only configs for all authenticated users"""
    
    queryset = AuctionConfig.objects.all()
    serializer_class = AuctionConfigSerializer
    permission_classes = [permissions.IsAuthenticated]


class AuctionEventViewSet(viewsets.ReadOnlyModelViewSet):
    """View auction activity log"""
    
    serializer_class = AuctionEventSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = StandardPagination
    
    def get_queryset(self):
        """Filter by auction_id if provided"""
        auction_id = self.request.query_params.get('auction_id')
        if auction_id:
            return AuctionEvent.objects.filter(auction_id=auction_id).order_by('-created_at')
        return AuctionEvent.objects.all().order_by('-created_at')
