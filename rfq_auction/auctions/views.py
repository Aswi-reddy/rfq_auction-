from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.utils import timezone
from django.contrib import messages
from django.http import JsonResponse

from auctions.models import Auction, Bid, AuctionEvent, AuctionConfig
from auctions.forms import (
    AuctioneerLoginForm, AuctioneerRegisterForm,
    BidderLoginForm, BidderRegisterForm,
    CreateAuctionForm, PlaceBidForm
)
from auctions.services.auction_engine import AuctionEngineService


# ========== LANDING ==========

def landing(request):
    """Landing page - choose role"""
    return render(request, 'landing.html')


# ========== AUCTIONEER FLOWS ==========

def auctioneer_register(request):
    """Auctioneer registration"""
    if request.method == 'POST':
        form = AuctioneerRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Registration successful! Welcome as Auctioneer.')
            return redirect('auctioneer_dashboard')
    else:
        form = AuctioneerRegisterForm()
    return render(request, 'auctioneer_register.html', {'form': form})


def auctioneer_login(request):
    """Auctioneer login"""
    if request.method == 'POST':
        form = AuctioneerLoginForm(request.POST)
        if form.is_valid():
            user = authenticate(
                username=form.cleaned_data['username'],
                password=form.cleaned_data['password']
            )
            if user and user.groups.filter(name='Auctioneer').exists():
                login(request, user)
                messages.success(request, f'Welcome back, {user.username}!')
                return redirect('auctioneer_dashboard')
            else:
                messages.error(request, 'Invalid auctioneer credentials')
    else:
        form = AuctioneerLoginForm()
    return render(request, 'auctioneer_login.html', {'form': form})


@login_required
def auctioneer_dashboard(request):
    """Auctioneer dashboard - manage auctions"""
    if not request.user.groups.filter(name='Auctioneer').exists():
        return redirect('landing')

    auctions = Auction.objects.filter(created_by=request.user)
    # Update all auction statuses based on current time
    for auction in auctions:
        auction.update_status()

    # Re-fetch after status updates
    auctions = Auction.objects.filter(created_by=request.user)
    total_bids = Bid.objects.filter(auction__created_by=request.user).count()

    return render(request, 'auctioneer_dashboard.html', {
        'auctions': auctions,
        'total_bids': total_bids,
        'total_auctions': auctions.count(),
    })


@login_required
def create_auction(request):
    """Auctioneer: Create new auction"""
    if not request.user.groups.filter(name='Auctioneer').exists():
        return redirect('landing')

    if request.method == 'POST':
        form = CreateAuctionForm(request.POST)
        if form.is_valid():
            auction = form.save(commit=True, created_by=request.user)

            # Log AUCTION_CREATED event
            AuctionEvent.objects.create(
                auction=auction,
                event_type='AUCTION_CREATED',
                description=f'Auction created: {auction.name}'
            )

            messages.success(request, 'Auction created successfully!')
            return redirect('auction_detail', auction_id=auction.id)
    else:
        form = CreateAuctionForm()

    return render(request, 'create_auction.html', {'form': form})


# ========== BIDDER FLOWS ==========

def bidder_register(request):
    """Bidder registration"""
    if request.method == 'POST':
        form = BidderRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Registration successful! Welcome as Bidder.')
            return redirect('bidder_dashboard')
    else:
        form = BidderRegisterForm()
    return render(request, 'bidder_register.html', {'form': form})


def bidder_login(request):
    """Bidder login"""
    if request.method == 'POST':
        form = BidderLoginForm(request.POST)
        if form.is_valid():
            user = authenticate(
                username=form.cleaned_data['username'],
                password=form.cleaned_data['password']
            )
            if user and user.groups.filter(name='Bidder').exists():
                login(request, user)
                messages.success(request, f'Welcome back, {user.username}!')
                return redirect('bidder_dashboard')
            else:
                messages.error(request, 'Invalid bidder credentials')
    else:
        form = BidderLoginForm()
    return render(request, 'bidder_login.html', {'form': form})


@login_required
def bidder_dashboard(request):
    """Bidder dashboard - view active auctions & my bids"""
    if not request.user.groups.filter(name='Bidder').exists():
        return redirect('landing')

    # Update all auction statuses based on current time
    for auction in Auction.objects.all():
        auction.update_status()

    active_auctions = Auction.objects.filter(status='ACTIVE')
    scheduled_auctions = Auction.objects.filter(status='SCHEDULED')
    all_open_auctions = Auction.objects.filter(status__in=['ACTIVE', 'SCHEDULED'])
    my_bids = Bid.objects.filter(bidder=request.user).select_related('auction')
    closed_auctions = Auction.objects.filter(status__in=['CLOSED', 'FORCE_CLOSED'])

    # Get rank info for current user's bids
    my_active_bids = []
    my_bid_rank = None
    for auction in active_auctions:
        my_bid = auction.bids.filter(bidder=request.user).order_by('-submitted_at').first()
        if my_bid:
            my_active_bids.append(my_bid)
            if my_bid_rank is None:
                rank = auction.get_bid_rank(my_bid)
                if rank:
                    my_bid_rank = rank

    return render(request, 'bidder_dashboard_new.html', {
        'active_auctions': active_auctions,
        'scheduled_auctions': scheduled_auctions,
        'all_open_auctions': all_open_auctions,
        'my_bids': my_bids,
        'my_active_bids': my_active_bids,
        'my_bid_rank': my_bid_rank,
        'closed_auctions': closed_auctions,
        'username': request.user.username,
    })


# ========== AUCTION DETAIL VIEWS ==========

@login_required
def auction_detail(request, auction_id):
    """Auctioneer: View auction details with live rankings"""
    if not request.user.groups.filter(name='Auctioneer').exists():
        return redirect('landing')

    auction = get_object_or_404(Auction, id=auction_id)
    auction.update_status()

    bids = auction.get_all_bids_ranked()
    events = auction.events.all().order_by('-created_at')[:50]

    return render(request, 'auction_detail_live.html', {
        'auction': auction,
        'bids': bids,
        'events': events,
        'my_bid': None,
        'user_role': 'auctioneer',
    })


@login_required
def bidder_auction_detail(request, auction_id):
    """Bidder: View auction details with own ranking"""
    if not request.user.groups.filter(name='Bidder').exists():
        return redirect('landing')

    auction = get_object_or_404(Auction, id=auction_id)
    auction.update_status()

    bids = auction.get_all_bids_ranked()
    events = auction.events.all().order_by('-created_at')[:50]
    my_bid = auction.bids.filter(bidder=request.user).order_by('-submitted_at').first()

    return render(request, 'auction_detail_live.html', {
        'auction': auction,
        'bids': bids,
        'events': events,
        'my_bid': my_bid,
        'user_role': 'bidder',
    })


@login_required
def auction_live_data(request, auction_id):
    """
    JSON API endpoint for live bid polling.
    Called by JavaScript every 5 seconds for real-time updates.
    """
    auction = get_object_or_404(Auction, id=auction_id)
    auction.update_status()

    rankings = AuctionEngineService.get_rankings(auction)

    events = auction.events.all().order_by('-created_at')[:20]
    events_data = [
        {
            'event_type': e.event_type,
            'event_type_display': e.get_event_type_display(),
            'description': e.description,
            'extension_reason': e.extension_reason,
            'created_at': e.created_at.isoformat(),
            'bidder': e.bidder.username if e.bidder else None,
        }
        for e in events
    ]

    best_bid = auction.get_best_bid()

    return JsonResponse({
        'status': auction.status,
        'status_display': auction.get_status_display(),
        'current_close_time': auction.get_effective_close_time().isoformat(),
        'forced_close_time': auction.forced_close_time.isoformat(),
        'total_extensions': auction.total_extensions,
        'bid_count': len(rankings),
        'lowest_bid': float(best_bid.total_cost) if best_bid else None,
        'lowest_bidder': best_bid.bidder.username if best_bid else None,
        'rankings': rankings,
        'events': events_data,
    })


@login_required
def place_bid(request, auction_id):
    """Bidder: Place or revise bid"""
    if not request.user.groups.filter(name='Bidder').exists():
        return redirect('landing')

    auction = get_object_or_404(Auction, id=auction_id)
    auction.update_status()

    existing_bid = auction.bids.filter(bidder=request.user).order_by('-submitted_at').first()

    if request.method == 'POST':
        form = PlaceBidForm(request.POST)
        if form.is_valid():
            result = AuctionEngineService.process_bid(
                auction_id=auction.id,
                bidder=request.user,
                price=form.cleaned_data.get('price'),
                freight=form.cleaned_data.get('freight_charges', 0) or 0,
                origin=form.cleaned_data.get('origin_charges', 0) or 0,
                destination=form.cleaned_data.get('destination_charges', 0) or 0,
                transit_days=form.cleaned_data.get('transit_time_days', 1),
                validity_days=form.cleaned_data.get('quote_validity_days', 30),
                carrier_name=form.cleaned_data.get('carrier_name')
            )

            if result['success']:
                if result.get('is_revision'):
                    messages.success(request, 'Bid revised successfully!')
                else:
                    messages.success(request, 'Bid placed successfully!')
                if result['l1_changed']:
                    messages.info(request, 'You are now the lowest bidder (L1)!')
                if result['extended']:
                    messages.info(request, f"Auction extended to {result['new_close_time'].strftime('%H:%M %d-%b')}")
                return redirect('bidder_auction_detail', auction_id=auction.id)
            else:
                messages.error(request, result['error'])
        else:
            messages.error(request, 'Please fix the form errors below.')
    else:
        if existing_bid:
            form = PlaceBidForm(initial={
                'carrier_name': existing_bid.carrier_name,
                'price': existing_bid.price,
                'freight_charges': existing_bid.freight_charges,
                'origin_charges': existing_bid.origin_charges,
                'destination_charges': existing_bid.destination_charges,
                'transit_time_days': existing_bid.transit_time_days,
                'quote_validity_days': existing_bid.quote_validity_days,
            })
        else:
            form = PlaceBidForm()

    return render(request, 'place_bid.html', {
        'form': form,
        'auction': auction,
        'existing_bid': existing_bid,
    })


def logout_view(request):
    """Logout"""
    logout(request)
    messages.success(request, 'Logged out successfully!')
    return redirect('landing')
