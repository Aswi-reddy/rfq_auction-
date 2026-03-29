import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'rfq_auction.settings')
django.setup()

from django.contrib.auth.models import User, Group
from auctions.models import AuctionConfig, Auction, Bid, AuctionEvent
from django.utils import timezone
from datetime import timedelta

print("🚀 Setting up test data for British Auction RFQ System...\n")

# Create groups
auctioneer_group, created = Group.objects.get_or_create(name='Auctioneer')
bidder_group, created = Group.objects.get_or_create(name='Bidder')
print("✅ Groups created: Auctioneer, Bidder")

# Create auctioneer user
auctioneer, created = User.objects.get_or_create(
    username='auctioneer1',
    defaults={
        'email': 'auctioneer@test.com',
        'first_name': 'John',
        'last_name': 'Smith',
        'is_staff': False,
        'is_active': True
    }
)
auctioneer.set_password('auctioneer123')
auctioneer.save()
auctioneer.groups.clear()
auctioneer.groups.add(auctioneer_group)
if created:
    print(f"✅ Auctioneer created: {auctioneer.username}")

# Create bidder users
bidders = []
for i in range(1, 4):
    bidder, created = User.objects.get_or_create(
        username=f'bidder{i}',
        defaults={
            'email': f'bidder{i}@company.com',
            'first_name': f'Supplier',
            'last_name': f'Company{i}',
            'is_staff': False,
            'is_active': True
        }
    )
    bidder.set_password('bidder123')
    bidder.save()
    bidder.groups.clear()
    bidder.groups.add(bidder_group)
    bidders.append(bidder)
    if created:
        print(f"✅ Bidder created: {bidder.username}")

print(f"\n✅ Created {len(bidders)} bidder users")

# Create auction configs (X and Y configurations)
configs = AuctionConfig.objects.all()
if not configs.exists():
    config1 = AuctionConfig.objects.create(
        trigger_window_x=10,
        extension_duration_y=5,
        trigger_type='BID_RECEIVED'
    )
    print(f"✅ Config 1 created: X={config1.trigger_window_x}min, Y={config1.extension_duration_y}min, Type=BID_RECEIVED")
    
    config2 = AuctionConfig.objects.create(
        trigger_window_x=15,
        extension_duration_y=10,
        trigger_type='L1_CHANGE'
    )
    print(f"✅ Config 2 created: X={config2.trigger_window_x}min, Y={config2.extension_duration_y}min, Type=L1_CHANGE")
else:
    config1 = configs.first()
    print(f"✅ Using existing config: X={config1.trigger_window_x}min, Y={config1.extension_duration_y}min, Type={config1.trigger_type}")

# Create test auction
now = timezone.now()
auction_name = 'RFQ-001: Transportation Services'
if not Auction.objects.filter(name=auction_name).exists():
    auction = Auction.objects.create(
        name=auction_name,
        description='Logistics and freight services for Pan-India delivery network',
        created_by=auctioneer,
        bid_start_time=now - timedelta(minutes=5),
        bid_close_time=now + timedelta(minutes=30),
        forced_close_time=now + timedelta(minutes=60),
        current_close_time=None,
        config=config1,
        status='ACTIVE',
        total_extensions=0
    )
    print(f"\n✅ Test Auction created: {auction.name}")
    print(f"   - Bid Close: {auction.bid_close_time.strftime('%H:%M:%S %d-%b')}")
    print(f"   - Forced Close: {auction.forced_close_time.strftime('%H:%M:%S %d-%b')}")
    
    # Create AUCTION_CREATED event
    AuctionEvent.objects.create(
        auction=auction,
        event_type='AUCTION_CREATED',
        description=f'Auction created by {auctioneer.username}'
    )
else:
    auction = Auction.objects.get(name=auction_name)
    print(f"\n✅ Test Auction already exists: {auction.name}")

print("\n" + "="*60)
print("🎯 TEST CREDENTIALS")
print("="*60)
print(f"\n👨‍💼 AUCTIONEER:")
print(f"   Username: auctioneer1")
print(f"   Password: auctioneer123")
print(f"   Email: auctioneer@test.com")

print(f"\n🏢 BIDDERS:")
for i in range(1, 4):
    print(f"   Bidder {i}:")
    print(f"      Username: bidder{i}")
    print(f"      Password: bidder123")
    print(f"      Email: bidder{i}@company.com")

print(f"\n📊 ACTIVE AUCTIONS:")
print(f"   Auction: {auction.name}")
print(f"   ID: {auction.id}")
print(f"   Status: {auction.status}")
print(f"   Time until close: ~30 minutes")

print("\n" + "="*60)
print("✅ Test data setup complete!")
print("="*60)
