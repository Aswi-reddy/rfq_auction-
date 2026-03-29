"""
BRITISH AUCTION ENGINE - PRODUCTION-GRADE LOGIC
================================================

This is the CORE of the system. Every bid goes through here.

Handles:
- Atomic bid placement with database row locking (select_for_update)
- Bid revisions (suppliers can lower their price multiple times)
- 3 trigger types: BID_RECEIVED, RANK_CHANGE, L1_CHANGE
- Live ranking by total_cost (latest bid per supplier)
- Extension capping (NEVER exceeds forced_close_time)
- Race condition prevention via @transaction.atomic
- Comprehensive event logging (audit trail)

Key Design Decisions:
- select_for_update() prevents concurrent bid conflicts
- Trigger window: (close_time - X minutes) to close_time
- Extensions capped at forced_close_time (hard stop)
- All prices stored as Decimal for financial precision
- Rankings based on latest bid per supplier, not all bids
"""

from django.db import transaction
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
from auctions.models import Auction, Bid, AuctionEvent


class AuctionEngineService:
    """
    British Auction Engine - All auction logic in one place.

    Stateless with static methods for easy testing.
    All DB writes use transactions with row-level locking.
    """

    # ====================================================================
    # VALIDATION LAYER
    # ====================================================================

    @staticmethod
    def validate_auction_open(auction):
        """
        CHECK #1: Is the auction still accepting bids?

        Validates:
        - Auction status is ACTIVE
        - Current time >= bid_start_time
        - Current time <= effective_close_time
        - Current time < forced_close_time

        Raises ValueError if any check fails.
        """
        now = timezone.now()
        close_time = auction.get_effective_close_time()

        # Check if auction is already in a terminal state (manually closed)
        # This MUST happen BEFORE update_status() to respect admin overrides
        if auction.status in ('CLOSED', 'FORCE_CLOSED'):
            raise ValueError(
                f"Auction is {auction.get_status_display()}, cannot accept bids"
            )

        # Auto-update status based on time
        auction.update_status()

        # Forced close check (absolute hard stop)
        if now >= auction.forced_close_time:
            raise ValueError(
                f"Auction forced closed at {auction.forced_close_time.strftime('%H:%M %d-%b')}. "
                f"No bids can be placed."
            )

        # Close time check
        if now > close_time:
            raise ValueError(
                f"Bidding closed at {close_time.strftime('%H:%M %d-%b')}. Cannot accept bids."
            )

        # Start time check
        if now < auction.bid_start_time:
            raise ValueError(
                f"Bidding hasn't started yet. Starts at {auction.bid_start_time.strftime('%H:%M %d-%b')}"
            )

        # Final status check
        if auction.status != 'ACTIVE':
            raise ValueError(f"Auction is {auction.get_status_display()}, cannot accept bids")

    @staticmethod
    def validate_bid_data(price, freight=0, origin=0, destination=0):
        """
        CHECK #2: Is the bid data valid?

        Rules:
        - All individual charges must be non-negative
        - Total cost (price + all charges) must be > 0

        NOTE: We do NOT require the new bid to be lower than L1.
        The spec says suppliers compete by lowering prices, but the system
        should accept any valid bid. Rankings handle the competition.
        """
        try:
            price_d = Decimal(str(price))
            freight_d = Decimal(str(freight))
            origin_d = Decimal(str(origin))
            destination_d = Decimal(str(destination))
        except Exception:
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

    # ====================================================================
    # BID PLACEMENT - MAIN METHOD (ATOMIC)
    # ====================================================================

    @staticmethod
    @transaction.atomic
    def process_bid(auction_id, bidder, price, freight=0, origin=0, destination=0,
                    transit_days=1, validity_days=30, carrier_name=None):
        """
        MAIN METHOD: Place or revise a bid on an auction.

        Wrapped in @transaction.atomic:
        - Either ALL operations succeed or NONE do (ACID)
        - select_for_update() acquires row-level lock preventing race conditions

        Flow:
        1. Lock auction row in DB (prevents concurrent bid conflicts)
        2. Validate auction is open for bidding
        3. Validate bid amounts (all positive, total > 0)
        4. Snapshot current L1 and rankings (BEFORE the new bid)
        5. Create or update bid (suppliers can revise!)
        6. Log BID_RECEIVED or BID_REVISED event
        7. Compute new L1 and rankings (AFTER the new bid)
        8. If L1 changed -> log L1_CHANGED event
        9. Check extension triggers -> extend + log EXTENDED event

        Returns dict:
            {
                success: bool,
                bid: Bid object,
                events: [AuctionEvent],
                l1_changed: bool,
                extended: bool,
                new_close_time: datetime,
                error: str (if failed)
            }
        """
        try:
            # STEP 1: LOCK
            # select_for_update() acquires an exclusive row lock on this auction.
            # Any other concurrent bid on the SAME auction will block here until
            # this transaction commits. This prevents race conditions.
            auction = Auction.objects.select_for_update().get(id=auction_id)

            # STEP 2: VALIDATE AUCTION
            AuctionEngineService.validate_auction_open(auction)

            # STEP 3: VALIDATE BID DATA
            price_d, freight_d, origin_d, destination_d = (
                AuctionEngineService.validate_bid_data(price, freight, origin, destination)
            )

            # STEP 4: SNAPSHOT - current state BEFORE this bid
            old_l1 = auction.get_best_bid()
            old_rankings = auction.get_all_bids_ranked()

            # STEP 5: CREATE OR UPDATE BID
            # Suppliers can revise their bids - we use the latest one for ranking.
            # We CREATE a new Bid row each time (preserving bid history).
            existing_bid = auction.bids.filter(bidder=bidder).order_by('-submitted_at').first()
            is_revision = existing_bid is not None

            bid = Bid.objects.create(
                auction=auction,
                bidder=bidder,
                price=price_d,
                freight_charges=freight_d,
                origin_charges=origin_d,
                destination_charges=destination_d,
                transit_time_days=int(transit_days),
                quote_validity_days=int(validity_days),
                carrier_name=carrier_name or "Unknown",
            )

            events = []

            # STEP 6: LOG BID EVENT
            event_type = 'BID_REVISED' if is_revision else 'BID_RECEIVED'
            event_desc = (
                f"{'Bid revised' if is_revision else 'New bid'} from {bidder.username} | "
                f"Carrier: {bid.carrier_name} | "
                f"Total: Rs.{bid.total_cost}"
            )
            if is_revision:
                event_desc += f" (was Rs.{existing_bid.total_cost})"

            bid_event = AuctionEvent.objects.create(
                auction=auction,
                event_type=event_type,
                description=event_desc,
                bidder=bidder
            )
            events.append(bid_event)

            # STEP 7: CHECK L1 CHANGE
            # Recalculate rankings AFTER this bid
            new_l1 = auction.get_best_bid()

            # L1 changed only if:
            # - There WAS a previous L1 (not first bid), AND
            # - The new L1 is a DIFFERENT bidder
            l1_changed = False
            if old_l1 is not None and new_l1 is not None:
                if new_l1.bidder_id != old_l1.bidder_id:
                    l1_changed = True

            if l1_changed:
                l1_event = AuctionEvent.objects.create(
                    auction=auction,
                    event_type='L1_CHANGED',
                    description=(
                        f"NEW LOWEST BIDDER: {new_l1.bidder.username} | "
                        f"Price: Rs.{new_l1.total_cost} | "
                        f"Carrier: {new_l1.carrier_name} | "
                        f"Previous L1: {old_l1.bidder.username} (Rs.{old_l1.total_cost})"
                    ),
                    bidder=new_l1.bidder
                )
                events.append(l1_event)

            # STEP 8: CHECK EXTENSION TRIGGERS
            should_extend, trigger_reason = AuctionEngineService._check_extension_triggers(
                auction, old_l1, new_l1, old_rankings
            )

            extension_happened = False
            if should_extend:
                ext_result = AuctionEngineService._execute_extension(auction, trigger_reason)
                if ext_result['success']:
                    extension_happened = True
                    ext_event = AuctionEvent.objects.create(
                        auction=auction,
                        event_type='EXTENDED',
                        description=(
                            f"AUCTION EXTENDED | "
                            f"Reason: {trigger_reason} | "
                            f"New Close: {ext_result['new_close_time'].strftime('%H:%M:%S %d-%b')}"
                            f"{' (CAPPED at forced close)' if ext_result.get('was_capped') else ''}"
                        ),
                        extension_reason=trigger_reason,
                        bidder=bidder
                    )
                    events.append(ext_event)

            # RETURN SUCCESS
            return {
                'success': True,
                'bid': bid,
                'events': events,
                'l1_changed': l1_changed,
                'extended': extension_happened,
                'new_close_time': auction.get_effective_close_time(),
                'total_extensions': auction.total_extensions,
                'is_revision': is_revision,
                'error': None,
            }

        except ValueError as validation_error:
            return {
                'success': False,
                'error': str(validation_error),
                'bid': None,
                'events': [],
                'l1_changed': False,
                'extended': False,
                'new_close_time': None,
                'total_extensions': None,
                'is_revision': False,
            }

        except Auction.DoesNotExist:
            return {
                'success': False,
                'error': 'Auction not found',
                'bid': None,
                'events': [],
                'l1_changed': False,
                'extended': False,
                'new_close_time': None,
                'total_extensions': None,
                'is_revision': False,
            }

        except Exception as unexpected_error:
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'error': f'Unexpected error: {str(unexpected_error)}',
                'bid': None,
                'events': [],
                'l1_changed': False,
                'extended': False,
                'new_close_time': None,
                'total_extensions': None,
                'is_revision': False,
            }

    # ====================================================================
    # EXTENSION TRIGGER LOGIC
    # ====================================================================

    @staticmethod
    def _check_extension_triggers(auction, old_l1, new_l1, old_rankings):
        """
        KEY LOGIC: Should the auction be extended?

        Implements all 3 trigger types from the British Auction spec:

        1) BID_RECEIVED
            -> Any bid placed in the trigger window causes extension.
            Most lenient - encourages maximum competition.

        2) RANK_CHANGE
            -> Extension only if any supplier's ranking position changed.
            Medium strictness - ignores bids that don't affect competition.

        3) L1_CHANGE
            -> Extension only when the LOWEST BIDDER changes.
            Most strict - only the very top matters.

        Pre-conditions checked:
        - Auction has config
        - Current time is within trigger window (close - X min to close)
        - Close time hasn't reached forced_close_time yet

        Returns: (should_extend: bool, reason: str)
        """
        config = auction.config
        if not config:
            return False, "No auction config"

        now = timezone.now()
        close_time = auction.get_effective_close_time()

        # TRIGGER WINDOW CHECK
        # The window is: (close_time - X minutes) to close_time
        trigger_window_start = close_time - timedelta(minutes=config.trigger_window_x)

        if not (trigger_window_start <= now <= close_time):
            return False, "Bid placed outside trigger window - no extension"

        # FORCED CLOSE SAFETY CHECK
        # If we've already extended to forced_close_time, cannot extend further
        if close_time >= auction.forced_close_time:
            return False, "Already at forced close time - cannot extend further"

        # EVALUATE TRIGGER TYPE
        if config.trigger_type == 'BID_RECEIVED':
            # Simplest: ANY bid in the trigger window triggers extension
            return True, f"Bid received in trigger window (last {config.trigger_window_x} min)"

        elif config.trigger_type == 'RANK_CHANGE':
            # Check if ANY supplier rank position changed
            new_rankings = auction.get_all_bids_ranked()
            if AuctionEngineService._rankings_changed(old_rankings, new_rankings):
                return True, f"Supplier rankings changed in trigger window (last {config.trigger_window_x} min)"
            return False, "No ranking change detected"

        elif config.trigger_type == 'L1_CHANGE':
            # Strictest: Only if the LOWEST BIDDER (L1) changed
            # First bid doesn't count as "change" - there was no previous L1
            if old_l1 is not None and new_l1 is not None:
                if new_l1.bidder_id != old_l1.bidder_id:
                    return True, (
                        f"L1 changed: {new_l1.bidder.username} (Rs.{new_l1.total_cost}) "
                        f"overtook {old_l1.bidder.username} (Rs.{old_l1.total_cost})"
                    )
            return False, "L1 did not change"

        return False, f"Unknown trigger type: {config.trigger_type}"

    @staticmethod
    def _rankings_changed(old_rankings, new_rankings):
        """
        Did ANY supplier ranking position change?

        Compares old vs new ranked bid lists by bidder_id at each position.
        Example:
          OLD: [L1: UserA, L2: UserB, L3: UserC]
          NEW: [L1: UserB, L2: UserA, L3: UserC]
          Returns: True (positions 1 and 2 changed)
        """
        if len(old_rankings) != len(new_rankings):
            return True  # Different number of bidders = ranking changed

        for old_bid, new_bid in zip(old_rankings, new_rankings):
            if old_bid.bidder_id != new_bid.bidder_id:
                return True

        return False

    @staticmethod
    def _execute_extension(auction, trigger_reason):
        """
        EXECUTE EXTENSION: Add Y minutes to close time.

        CRITICAL RULE from spec:
        "Extensions MUST NEVER exceed forced_close_time"

        Logic:
          new_close = current_close + Y minutes
          if new_close > forced_close:
              new_close = forced_close  (cap it)

          Only update if new_close > current_close
        """
        config = auction.config
        if not config:
            return {'success': False, 'new_close_time': None}

        current_close = auction.get_effective_close_time()
        extension = timedelta(minutes=config.extension_duration_y)
        tentative_new_close = current_close + extension

        # CRITICAL: Cap at forced_close_time
        final_new_close = min(tentative_new_close, auction.forced_close_time)
        was_capped = (final_new_close == auction.forced_close_time)

        # Only extend if actually adding time
        if final_new_close > current_close:
            auction.current_close_time = final_new_close
            auction.total_extensions += 1
            auction.save(update_fields=['current_close_time', 'total_extensions', 'updated_at'])

            actual_extension_minutes = (final_new_close - current_close).total_seconds() / 60

            return {
                'success': True,
                'new_close_time': final_new_close,
                'extension_minutes': actual_extension_minutes,
                'was_capped': was_capped,
            }

        return {'success': False, 'new_close_time': current_close}

    # ====================================================================
    # RANKING QUERIES
    # ====================================================================

    @staticmethod
    def get_rankings(auction):
        """
        Get LIVE rankings of all suppliers.

        Uses latest bid per supplier, sorted by:
        1. total_cost ASCENDING (lowest = L1 = best)
        2. submitted_at ASCENDING (earliest wins ties)
        """
        ranked_bids = auction.get_all_bids_ranked()

        rankings = []
        for rank, bid in enumerate(ranked_bids, start=1):
            rankings.append({
                'rank': rank,
                'label': f'L{rank}',
                'bid_id': bid.id,
                'bidder_id': bid.bidder_id,
                'bidder_name': bid.bidder.username,
                'carrier_name': bid.carrier_name,
                'base_price': float(bid.price),
                'freight_charges': float(bid.freight_charges),
                'origin_charges': float(bid.origin_charges),
                'destination_charges': float(bid.destination_charges),
                'total_cost': float(bid.total_cost),
                'transit_days': bid.transit_time_days,
                'validity_days': bid.quote_validity_days,
                'submitted_at': bid.submitted_at.isoformat(),
                'is_l1': rank == 1,
            })

        return rankings

    @staticmethod
    def get_auction_status_summary(auction):
        """
        Get comprehensive auction state for UI display.
        Returns everything needed for dashboard/detail pages.
        """
        auction.update_status()
        best_bid = auction.get_best_bid()

        return {
            'auction_id': auction.id,
            'name': auction.name,
            'description': auction.description,
            'status': auction.status,
            'status_display': auction.get_status_display(),
            'bid_start_time': auction.bid_start_time.isoformat(),
            'bid_close_time': auction.bid_close_time.isoformat(),
            'current_close_time': auction.get_effective_close_time().isoformat(),
            'forced_close_time': auction.forced_close_time.isoformat(),
            'total_bids': auction.bids.count(),
            'unique_bidders': auction.bids.values('bidder').distinct().count(),
            'total_extensions': auction.total_extensions,
            'l1_price': float(best_bid.total_cost) if best_bid else None,
            'l1_bidder': best_bid.bidder.username if best_bid else None,
            'l1_carrier': best_bid.carrier_name if best_bid else None,
            'config': {
                'trigger_window_x': auction.config.trigger_window_x,
                'extension_duration_y': auction.config.extension_duration_y,
                'trigger_type': auction.config.trigger_type,
                'trigger_type_display': auction.config.get_trigger_type_display(),
            } if auction.config else None,
        }
