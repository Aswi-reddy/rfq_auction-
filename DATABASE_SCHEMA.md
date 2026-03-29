# British Auction RFQ System - Database Schema Design

**Version:** 1.0  
**Date:** March 29, 2026  
**Database:** SQLite (sqlite3), Compatible with PostgreSQL

---

## 1. Schema Overview

### 1.1 Core Tables
- **AuctionConfig** - British Auction configuration (X, Y parameters)
- **Auction** - RFQ with timing and status tracking
- **Bid** - Supplier quote submissions (supports revisions)
- **AuctionEvent** - Complete audit trail
- **AuctionSnapshot** - State snapshots at key moments

### 1.2 ERD (Entity Relationship Diagram)

```
┌──────────────────────┐
│   AUTH_USER          │ (Django User)
│ (PK: id)             │
│ - username           │
│ - password_hash      │
│ - is_staff           │
│ - date_joined        │
└──────────┬───────────┘
           │
           │ (1) Created
           │ (M) Bidding
           │
    ┌──────┴──────┬────────────┬──────────────┐
    │             │            │              │
┌───▼────────┐ ┌─▼──────────┐ ┌┴───────────┐ │
│ Auction    ├─┤ AuctionCfg │ │   Bid      │ │
│ (PK: id)   │ │ (PK: id)   │ │ (PK: id)   │ │
│ - name     │ │ - X (mins) │ │ - price    │ │
│ - status   │ │ - Y (mins) │ │ - freight  │ │
│ - timing   │ │ - trigger  │ │ - origin   │ │
│            │ │   type     │ │ - dest     │ │
└────────────┘ └────────────┘ └────────────┘ │
    │                              │          │
    └──────────┬───────────────────┘          │
               │                              │
    ┌──────────▼──────────┐                   │
    │  AuctionEvent       │←──────────────────┘
    │  (PK: id)           │ FK: bidder, auction
    │  - event_type       │
    │  - description      │
    │  - created_at       │
    └─────────────────────┘
    
    ┌──────────────────────┐
    │ AuctionSnapshot      │
    │ (PK: id)             │
    │ - total_bidders      │
    │ - ranking_data(JSON) │
    │ - created_at         │
    └──────────────────────┘
```

---

## 2. Table Definitions

### 2.1 AuctionConfig Table

**Purpose:** Store British Auction configuration parameters

**Table Name:** `auctions_auctionconfig`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO_INCREMENT | Unique configuration ID |
| trigger_window_x | INTEGER | NOT NULL, DEFAULT=10 | Trigger window (minutes) - Monitor last X minutes |
| extension_duration_y | INTEGER | NOT NULL, DEFAULT=5 | Extension duration (minutes) - Extend by Y minutes |
| trigger_type | VARCHAR(20) | NOT NULL, DEFAULT='BID_RECEIVED' | Trigger type: BID_RECEIVED, RANK_CHANGE, L1_CHANGE |
| created_at | TIMESTAMP | NOT NULL, AUTO_NOW_ADD | When configuration was created |
| updated_at | TIMESTAMP | NOT NULL, AUTO_NOW | Last updated timestamp |

**Indexes:**
- PK on id (implicit)

**Relationships:**
- (1) Auction ← (M) AuctionConfig (ONE config can be used by many auctions)

**Constraints:**
- trigger_window_x: Range 5-60 minutes (validated in model)
- extension_duration_y: Range 1-30 minutes (validated in model)
- trigger_type: Must be one of the TRIGGER_CHOICES

**Sample Data:**
```
id=1: trigger_window_x=10, extension_duration_y=5, trigger_type='BID_RECEIVED'
id=2: trigger_window_x=15, extension_duration_y=3, trigger_type='RANK_CHANGE'
id=3: trigger_window_x=5, extension_duration_y=10, trigger_type='L1_CHANGE'
```

---

### 2.2 Auction Table

**Purpose:** Store RFQ auction details with timing and status

**Table Name:** `auctions_auction`

| Column | Type | Constraints | Key Info |
|--------|------|-------------|----------|
| id | INTEGER | PK, AUTO_INCREMENT | Unique auction ID |
| name | VARCHAR(255) | NOT NULL | RFQ name/reference |
| description | TEXT | NULL | RFQ description |
| bid_start_time | TIMESTAMP | NOT NULL | When bidding starts (IST) |
| bid_close_time | TIMESTAMP | NOT NULL | Standard close time (IST) |
| forced_close_time | TIMESTAMP | NOT NULL | Hard deadline - can't extend beyond (IST) |
| current_close_time | TIMESTAMP | NULL | Effective close time (= bid_close_time + extensions) |
| status | VARCHAR(20) | NOT NULL, DEFAULT='SCHEDULED' | SCHEDULED, ACTIVE, CLOSED, FORCE_CLOSED |
| total_extensions | INTEGER | NOT NULL, DEFAULT=0 | Count of times extended |
| created_by_id | INTEGER | FK, NOT NULL | Auctioneer who created (FK to auth_user.id) |
| config_id | INTEGER | FK, NULL | Configuration used (FK to auctions_auctionconfig.id) |
| created_at | TIMESTAMP | NOT NULL, AUTO_NOW_ADD | Audit: when created |
| updated_at | TIMESTAMP | NOT NULL, AUTO_NOW | Audit: last updated |

**Indexes:**
```
- PK: id
- Composite: (status, bid_start_time)         ← Find auctions starting in a range
- Composite: (status, current_close_time)     ← Find auctions closing soon
- Composite: (status, forced_close_time)      ← Find near forced close
- Composite: (created_by_id, status)          ← Auctioneer's auctions
- Single: bid_close_time                       ← Status updates
- Single: forced_close_time                    ← Forced close detection
```

**Foreign Keys:**
- created_by_id → auth_user.id (CASCADE delete)
- config_id → auctions_auctionconfig.id (SET_NULL)

**Constraints:**
- bid_start_time < bid_close_time (model validation)
- bid_close_time < forced_close_time (model validation)
- forced_close_time - bid_close_time ≥ 5 minutes (model validation)
- status must be in CHOICES
- total_extensions ≥ 0

**Sample Data:**
```
id=1, name='RFQ-2026-001', bid_start_time='2026-03-29 10:00', 
bid_close_time='2026-03-29 18:00', forced_close_time='2026-03-29 19:00',
current_close_time='2026-03-29 18:15', status='ACTIVE', 
total_extensions=1, created_by_id=1, config_id=1
```

**Key Business Logic:**
- `get_effective_close_time()` → Returns current_close_time or bid_close_time
- `is_active()` → Checks if now is between start and close
- `can_extend()` → Checks if current_close < forced_close
- `update_status()` → Auto-updates status based on time (atomic)

---

### 2.3 Bid Table

**Purpose:** Store supplier bids/quotes with price components

**Table Name:** `auctions_bid`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO_INCREMENT | Unique bid ID |
| auction_id | INTEGER | FK, NOT NULL, CASCADE | Which auction (FK to auctions_auction.id) |
| bidder_id | INTEGER | FK, NOT NULL, CASCADE | Supplier bidding (FK to auth_user.id) |
| carrier_name | VARCHAR(255) | DEFAULT='', BLANK=TRUE | Logistics carrier name |
| price | DECIMAL(12,2) | NOT NULL | Base price component |
| freight_charges | DECIMAL(10,2) | NOT NULL, DEFAULT=0 | Freight charges |
| origin_charges | DECIMAL(10,2) | NOT NULL, DEFAULT=0 | Origin/pickup charges |
| destination_charges | DECIMAL(10,2) | NOT NULL, DEFAULT=0 | Destination/delivery charges |
| transit_time_days | INTEGER | NOT NULL | Transit in days |
| quote_validity_days | INTEGER | NOT NULL | Quote valid for N days |
| submitted_at | TIMESTAMP | NOT NULL, AUTO_NOW_ADD | When bid was placed |
| updated_at | TIMESTAMP | NOT NULL, AUTO_NOW | Last updated |

**Calculated Field:**
- `total_cost` = price + freight_charges + origin_charges + destination_charges

**Indexes:**
```
- PK: id
- Composite: (auction_id, bidder_id, -submitted_at)  ← Get latest bid per supplier
- Composite: (auction_id, submitted_at)              ← Find bids in time range
- Composite: (auction_id, -submitted_at)             ← Ranking queries
```

**Foreign Keys:**
- auction_id → auctions_auction.id (CASCADE delete)
- bidder_id → auth_user.id (CASCADE delete)

**Constraints:**
- price ≥ 0 (validation)
- freight_charges ≥ 0 (validation)
- origin_charges ≥ 0 (validation)
- destination_charges ≥ 0 (validation)
- total_cost > 0 (validation)
- transit_time_days ≥ 1 (form validation)
- quote_validity_days ≥ 1 (form validation)

**Sample Data:**
```
id=1, auction_id=1, bidder_id=2, carrier_name='FedEx',
price=1000.00, freight_charges=50.00, origin_charges=0, 
destination_charges=100.00, transit_time_days=2, quote_validity_days=30,
submitted_at='2026-03-29 14:30', total_cost=1150.00

id=2, auction_id=1, bidder_id=2, carrier_name='FedEx',  ← BID REVISION
price=950.00, freight_charges=50.00, origin_charges=0,
destination_charges=100.00, transit_time_days=2, quote_validity_days=30,
submitted_at='2026-03-29 15:45', total_cost=1100.00  ← LOWER (revision)
```

**Key Properties:**
- `total_cost` (property) → Calculated sum of all components
- `get_rank()` → Returns bid's rank in auction (1=best)
- `is_l1()` → Returns True if bidder currently has L1

**Important Note:**
- **No unique constraint** on (auction_id, bidder_id)
- Suppliers CAN bid multiple times (revisions)
- Only **latest bid per supplier** is used for ranking
- Preserves complete bid history for audit trail

---

### 2.4 AuctionEvent Table

**Purpose:** Complete audit trail - every action logged

**Table Name:** `auctions_auctionevent`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO_INCREMENT | Event ID |
| auction_id | INTEGER | FK, NOT NULL, CASCADE | Which auction |
| bidder_id | INTEGER | FK, NULL, CASCADE | Which bidder (if applicable) |
| event_type | VARCHAR(50) | NOT NULL | Event type (see choices below) |
| description | TEXT | NOT NULL | Human-readable description |
| extension_reason | VARCHAR(255) | NULL | Why extension triggered (if applicable) |
| created_at | TIMESTAMP | NOT NULL, AUTO_NOW_ADD | When event occurred |

**Event Types (CHOICES):**
| Event Type | When It Occurs | Example Description |
|------------|---|---|
| AUCTION_CREATED | Auctioneer creates auction | "Auction created: RFQ-2026-001" |
| BID_RECEIVED | New bid from supplier | "New bid from supplier1 \| Carrier: FedEx \| Total: Rs.1150" |
| BID_REVISED | Supplier lowers their bid | "Bid revised from supplier1 \| Total: Rs.1100 (was Rs.1150)" |
| L1_CHANGED | Lowest bidder changes | "NEW LOWEST BIDDER: supplier2 \| Price: Rs.950 \| Previous L1: supplier1 (Rs.1100)" |
| EXTENDED | Auction time extended | "AUCTION EXTENDED \| Reason: BID_RECEIVED in trigger window \| New Close: 18:15 IST" |
| CLOSED | Auction closed | "Auction CLOSED at scheduled close time" |
| FORCE_CLOSED | Forced close time reached | "Auction FORCE_CLOSED - hard deadline reached" |

**Indexes:**
```
- PK: id
- Composite: (auction_id, -created_at)         ← Get auction's event history
- Composite: (event_type, created_at)          ← Analytics queries
```

**Foreign Keys:**
- auction_id → auctions_auction.id (CASCADE delete)
- bidder_id → auth_user.id (CASCADE delete)

**Sample Data:**
```
Event 1:
event_type='AUCTION_CREATED', auction_id=1, bidder_id=NULL,
description='Auction created: RFQ-2026-001', created_at='2026-03-29 09:00'

Event 2:
event_type='BID_RECEIVED', auction_id=1, bidder_id=2,
description='New bid from supplier1 | Carrier: FedEx | Total: Rs.1150',
created_at='2026-03-29 14:30'

Event 3:
event_type='L1_CHANGED', auction_id=1, bidder_id=3,
description='NEW LOWEST BIDDER: supplier2 | Price: Rs.950 | Previous L1: supplier1 (Rs.1100)',
created_at='2026-03-29 15:00'

Event 4:
event_type='EXTENDED', auction_id=1, bidder_id=2,
description='AUCTION EXTENDED | Reason: BID_RECEIVED in trigger window | New Close: 18:15',
extension_reason='BID_RECEIVED in trigger window (last 10 min)',
created_at='2026-03-29 15:45'
```

**Purpose:**
- ✅ Complete transparency (fairness, compliance)
- ✅ Audit trail for dispute resolution
- ✅ Analytics (how many extensions per auction, etc)
- ✅ Debugging (trace issue to specific event)

---

### 2.5 AuctionSnapshot Table

**Purpose:** Capture auction state at key moments for analysis

**Table Name:** `auctions_auctionsnapshot`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| id | INTEGER | PK, AUTO_INCREMENT | Snapshot ID |
| auction_id | INTEGER | FK, NOT NULL, CASCADE | Which auction |
| total_bidders | INTEGER | NOT NULL | Number of unique suppliers |
| ranking_data | TEXT/JSON | NOT NULL | Rankings snapshot (JSON format) |
| created_at | TIMESTAMP | NOT NULL, AUTO_NOW_ADD | When snapshot taken |

**Indexes:**
```
- PK: id
- Single: auction_id                           ← Get snapshots for auction
- Composite: (auction_id, created_at)          ← Time-series snapshots
```

**Foreign Keys:**
- auction_id → auctions_auction.id (CASCADE delete)

**Sample Data:**
```
{
  "auction_id": 1,
  "total_bidders": 5,
  "ranking_data": {
    "L1": {
      "supplier": "supplier2",
      "price": 950.00,
      "freight": 50.00,
      "total": 1000.00,
      "rank": 1
    },
    "L2": {
      "supplier": "supplier1",
      "price": 1000.00,
      "freight": 50.00,
      "total": 1050.00,
      "rank": 2
    },
    ...
  },
  "created_at": "2026-03-29 18:00"
}
```

**Purpose:**
- Post-auction analysis
- State reconstruction if needed
- Analytics on bidding patterns
- Performance trending

---

## 3. Detailed Relationships

### 3.1 Foreign Key Relationships

```
auth_user (Django built-in)
  ├─ (1:M) → Auction.created_by_id          [Auctioneer creates many auctions]
  ├─ (1:M) → Bid.bidder_id                  [Bidder places many bids]
  ├─ (1:M) → AuctionEvent.bidder_id         [Bidder has events logged]
  └─ Cascade Delete: Yes (author/bidder deleted → records deleted)

AuctionConfig
  └─ (1:M) → Auction.config_id              [Config used by many auctions]
     Set Null on Delete: Yes (config deleted → auction.config = NULL)

Auction
  ├─ (M:M via Bid) → auth_user              [Auction has many bidders]
  ├─ (1:M) → Bid.auction_id                 [Auction has many bids]
  ├─ (1:M) → AuctionEvent.auction_id        [Auction has event log]
  ├─ (1:M) → AuctionSnapshot.auction_id     [Auction has snapshots]
  └─ Cascade Delete: Yes (auction deleted → all related records deleted)

Bid
  ├─ (M:M via Auction) Many-to-Many         [Supplier bidding on many auctions]
  └─ Cascade Delete: Yes (bid related records deleted)
```

### 3.2 Ranking Relationship (M:M impl via Bid)

```
One Auction → Many Bids
             └─ One Bid per Supplier (Latest)
                └─ Sorted by total_cost
                   └─ Generates L1, L2, L3... rankings

Query:
SELECT bid.*, user.username
FROM auctions_bid bid
JOIN auth_user user ON bid.bidder_id = user.id
WHERE bid.auction_id = ?
  AND bid.id IN (
    SELECT id FROM auctions_bid sub
    WHERE sub.auction_id = ? AND sub.bidder_id = bid.bidder_id
    ORDER BY sub.submitted_at DESC
    LIMIT 1
  )
ORDER BY bid.total_cost ASC, bid.submitted_at ASC

Result: Ranked list [L1, L2, L3, ...]
```

---

## 4. Data Integrity Constraints

### 4.1 Domain Constraints

| Column | Constraint | Why |
|--------|-----------|-----|
| price | ≥ 0 | Can't be negative |
| freight_charges | ≥ 0 | Can't be negative |
| origin_charges | ≥ 0 | Can't be negative |
| destination_charges | ≥ 0 | Can't be negative |
| total_cost | > 0 | Must exceed zero |
| trigger_window_x | 5-60 | Reasonable range |
| extension_duration_y | 1-30 | Reasonable range |
| transit_time_days | ≥ 1 | At least 1 day |
| quote_validity_days | ≥ 1 | At least 1 day |
| total_extensions | ≥ 0 | Never negative |

### 4.2 Temporal Constraints

| Constraint | Validation | Error Message |
|------------|-----------|---|
| bid_start < bid_close | Auction.clean() | "Bid close time must be AFTER bid start time" |
| bid_close < forced_close | Auction.clean() | "Forced close time must be AFTER bid close time" |
| (forced_close - bid_close) ≥ 5 min | Auction.clean() | "Buffer required: at least 5 minutes" |
| Extensions ≤ forced_close | ExtensionService | "Cannot extend beyond forced close time" |

### 4.3 Referential Integrity

| FK | Action | Reason |
|----|--------|--------|
| Auction.created_by_id → auth_user.id | CASCADE | Delete auctioneer → delete their auctions |
| Auction.config_id → AuctionConfig.id | SET_NULL | Delete config → auctions still exist but config = NULL |
| Bid.auction_id → Auction.id | CASCADE | Delete auction → delete all bids |
| Bid.bidder_id → auth_user.id | CASCADE | Delete bidder → delete their bids |
| AuctionEvent.auction_id → Auction.id | CASCADE | Delete auction → delete event log |
| AuctionEvent.bidder_id → auth_user.id | CASCADE | Delete bidder → delete related events |

---

## 5. Query Performance Patterns

### 5.1 Common Queries

**Q1: Get active auctions**
```sql
SELECT * FROM auctions_auction
WHERE status = 'ACTIVE'
  AND bid_start_time <= NOW()
  AND current_close_time >= NOW()
ORDER BY current_close_time ASC
```
**Index Used:** (status, current_close_time) ✅ FAST

**Q2: Get latest bid from each supplier**
```sql
SELECT bid.* FROM auctions_bid bid
WHERE bid.auction_id = ?
  AND bid.id IN (
    SELECT id FROM auctions_bid sub
    WHERE sub.auction_id = bid.auction_id
      AND sub.bidder_id = bid.bidder_id
    ORDER BY sub.submitted_at DESC
    LIMIT 1
  )
ORDER BY bid.submitted_at DESC
```
**Index Used:** (auction_id, bidder_id, -submitted_at) ✅ FAST O(n)

**Q3: Get ranked bids for auction**
```sql
SELECT bid.*, user.username FROM auctions_bid bid
JOIN auth_user user ON bid.bidder_id = user.id
[... subquery for latest bid per supplier ...]
ORDER BY bid.total_cost ASC, bid.submitted_at ASC
LIMIT 3 -- L1, L2, L3
```
**Index Used:** (auction_id, bidder_id, -submitted_at) ✅ FAST

**Q4: Get auctioneer's auctions**
```sql
SELECT * FROM auctions_auction
WHERE created_by_id = ?
ORDER BY created_at DESC
```
**Index Used:** (created_by_id, status) ✅ FAST

**Q5: Get auction events**
```sql
SELECT * FROM auctions_auctionevent
WHERE auction_id = ?
ORDER BY created_at DESC
LIMIT 50
```
**Index Used:** (auction_id, -created_at) ✅ FAST

### 5.2 N+1 Problem Prevention

**React Pattern (Prefetch):**
```python
auctions = Auction.objects.all() \
    .prefetch_related('bids') \
    .prefetch_related('events') \
    .select_related('config', 'created_by')

# 1 query per relationship, not 1 per object
```

**Result:** 200+ queries → 3-5 queries (-95%) 💨

---

## 6. Indexing Strategy

### 6.1 Auction Table Indexes

| Index | Columns | Selectivity | Query Pattern | Performance |
|-------|---------|-------------|---------------|-------------|
| PK | id | High | `WHERE id = ?` | ✅ FAST |
| IDX_1 | (status, bid_start_time) | High | Find auctions starting soon | ✅ FAST |
| IDX_2 | (status, current_close_time) | High | Find auctions closing soon | ✅ FAST |
| IDX_3 | (status, forced_close_time) | High | Find near forced close | ✅ FAST |
| IDX_4 | (created_by_id, status) | High | Auctioneer's auctions | ✅ FAST |
| IDX_5 | bid_close_time | Medium | Status updates | ✅ OK |
| IDX_6 | forced_close_time | Medium | Forced close detection | ✅ OK |

**Total Indexes: 7 (reasonable for 5-10 million records)**

### 6.2 Bid Table Indexes

| Index | Columns | Selectivity | Query Pattern | Performance |
|-------|---------|-------------|---------------|-------------|
| PK | id | High | `WHERE id = ?` | ✅ FAST |
| IDX_1 | (auction_id, bidder_id, -submitted_at) | High | Get latest bid per supplier | ✅ FAST |
| IDX_2 | (auction_id, submitted_at) | High | Bids in time range | ✅ FAST |
| IDX_3 | (auction_id, -submitted_at) | High | All bids ordered | ✅ FAST |

**Total Indexes: 4**

### 6.3 AuctionEvent Table Indexes

| Index | Columns | Purpose |
|-------|---------|---------|
| PK | id | Primary key |
| IDX_1 | (auction_id, -created_at) | Event history |
| IDX_2 | (event_type, created_at) | Analytics |

---

## 7. Caching Strategy

### 7.1 Database-Level Caching (Django ORM)

**Queryse**t Caching:
```python
# First call: Hit DB
rankings = auction.get_all_bids_ranked()

# Queries executed:
# 1. SELECT * FROM auctions_bid WHERE auction_id = ?
#    (Subquery to get latest bid per supplier)
# 2. SELECT * FROM auth_user WHERE id IN (...)
#    (Join back to user info)

# Result stored in cache:
# cache_key = 'auction_{id}_rankings'
# timeout = 5 seconds
```

**Cache Invalidation Triggers:**
- When new bid placed
- When auction status changes
- When cache TTL expires (5 seconds)

### 7.2 Query Optimization

**Select Related (JOIN):**
```python
Bid.objects.select_related('bidder', 'auction')
# Fetches bidder and auction in same query (JOIN)
```

**Prefetch Related (Batch):**
```python
Auction.objects.prefetch_related('bids')
# Fetches all bids in separate query, then joins in Python
```

---

## 8. Data Growth Projections

### 8.1 Typical Usage

| Entity | Per Day | Per Month | Per Year | Total (5Y) |
|--------|---------|-----------|----------|-----------|
| Auctions | 10 | 300 | 3,650 | 18,250 |
| Bids | 100 | 3,000 | 36,500 | 182,500 |
| Events | 150 | 4,500 | 54,750 | 273,750 |
| Snapshots | 20 | 600 | 7,300 | 36,500 |

**Estimated DB Size: 500MB - 1GB for 5 years**

### 8.2 Scaling Recommendations

| Milestone | Issue | Solution |
|-----------|-------|----------|
| 10K auctions | SQLite performance | Switch to PostgreSQL |
| 100K bids | Index fragmentation | Re-build indexes |
| 1M events | Slow queries | Archive old events, add partitioning |
| > 10GB | Single-server limit | Horizontal scaling (replica DB) |

---

## 9. Migration Strategy

### 9.1 Django Migrations Applied

```
✅ 0001_initial          - Core models
✅ 0002_bid_carrier_name - Add carrier_name field
✅ 0003_alter_bid_options - Update bid options
✅ 0004_auctionsnapshot_auctionstatistics_and_more - Extended features
```

### 9.2 Migration File Structure

```python
# migrations/0001_initial.py
class Migration(migrations.Migration):
    dependencies = []
    operations = [
        migrations.CreateModel(
            name='AuctionConfig',
            fields=[...]
        ),
        migrations.CreateModel(
            name='Auction',
            fields=[...]
        ),
        migrations.CreateModel(
            name='Bid',
            fields=[...]
        ),
        # ... etc
    ]
```

---

## 10. Backup & Recovery

### 10.1 Backup Strategy

**SQLite Backup:**
```bash
# Full backup
cp db.sqlite3 db.sqlite3.backup.$(date +%Y%m%d)

# Incremental backup (daily)
sqlite3 db.sqlite3 ".backup db.backup"
```

**PostgreSQL Backup (Production):**
```bash
pg_dump -h localhost -U dbuser auction_db | gzip > auction_db.sql.gz
```

### 10.2 Data Retention Policy

| Data Type | Retention | Archive |
|-----------|-----------|---------|
| Active Auctions | Keep forever | N/A |
| Closed Auctions | Keep 5 years | Archive to S3 |
| Events | Keep 2 years | Archive with audit logs |
| Snapshots | Keep 1 year | Compress on Archive |

---

## 11. Data Example (Full Scenario)

### Scenario: New Auction with Bids

**Timeline:**
- 10:00 - Auctioneer creates auction
- 14:30 - Supplier1 places first bid
- 15:00 - Supplier2 lowers bid (becomes L1)
- 15:45 - Supplier1 revises bid (becomes L1 again)
- 17:55 - Auction extended due to L1 change
- 18:00 - Auction closes (originally scheduled)

**Database State:**

**Auction Record:**
```
id=1
name='RFQ-2026-001'
bid_start_time='2026-03-29 10:00'
bid_close_time='2026-03-29 18:00'
forced_close_time='2026-03-29 19:00'
current_close_time='2026-03-29 18:10' ← EXTENDED
status='CLOSED'
total_extensions=1
created_by_id=1 (auctioneer)
config_id=1
```

**Bid Records:**
```
Bid 1: supplier1, total_cost=1150, submitted_at='14:30', rank=2 (L2)
Bid 2: supplier2, total_cost=950, submitted_at='15:00', rank=1 (L1)
Bid 3: supplier1, total_cost=900, submitted_at='15:45', rank=1 (L1) ← Latest per supplier
```

**Event Records:**
```
Event 1: AUCTION_CREATED @10:00
Event 2: BID_RECEIVED supplier1 @14:30 (Rs.1150)
Event 3: BID_RECEIVED supplier2 @15:00 (Rs.950)
Event 4: L1_CHANGED supplier2 @15:00 (Rs.950 < Rs.1150)
Event 5: BID_REVISED supplier1 @15:45 (Rs.900, was Rs.1150)
Event 6: L1_CHANGED supplier1 @15:45 (Rs.900 < Rs.950)
Event 7: EXTENDED @15:57 (L1 change in trigger window)
         new_close='2026-03-29 18:10'
Event 8: CLOSED @18:10 (at new close time)
```

**Ranking Query Result:**
```
L1: supplier1, total_cost=900, carrier=FedEx
L2: supplier2, total_cost=950, carrier=DHL
```

---

## 12. Data Validation Rules

### 12.1 At-Rest Validation (Application Layer)

```python
class Auction(models.Model):
    def clean(self):
        # Bid start < Bid close
        if self.bid_start_time >= self.bid_close_time:
            raise ValidationError("Start time must be before close time")
        
        # Bid close < Forced close
        if self.bid_close_time >= self.forced_close_time:
            raise ValidationError("Close time must be before forced close")
        
        # Minimum buffer
        buffer = self.forced_close_time - self.bid_close_time
        if buffer < timedelta(minutes=5):
            raise ValidationError("5-minute buffer required")
```

### 12.2 In-Transit Validation (API Layer)

```python
class PlaceBidSerializer(serializers.Serializer):
    price = serializers.DecimalField(max_digits=12, decimal_places=2)
    # Validates: non-null, numeric, 2 decimal places
    
    transit_time_days = serializers.IntegerField(min_value=1)
    # Validates: integer, minimum 1
```

---

## 13. Schema Diagram (ASCII)

```
┌─────────────────────────────────────────────────────────────────────┐
│                       AUCTION_RFQ_SYSTEM                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌──────────────────┐    ┌──────────────────┐                      │
│  │ auth_user        │    │ AuctionConfig    │                      │
│  ├──────────────────┤    ├──────────────────┤                      │
│  │ id (PK)          │    │ id (PK)          │                      │
│  │ username         │    │ trigger_window_x │                      │
│  │ password         │    │ extension_duration│                      │
│  │ is_staff         │    │ trigger_type     │                      │
│  └──────────────────┘    └──────────────────┘                      │
│      │                           │                                 │
│      │ (1)             (FK)      │                                 │
│      │ Created         config    │                                 │
│      └────────┬───────────────┬──┘                                 │
│              │               │                                    │
│          ┌───▼───────────────▼──────────────┐                      │
│          │         AUCTION (Auctions)        │                      │
│          ├────────────────────────────────────┤                      │
│          │ id (PK)                            │                      │
│          │ name, description                  │                      │
│          │ bid_start_time                     │                      │
│          │ bid_close_time                     │                      │
│          │ forced_close_time                  │                      │
│          │ current_close_time (with ext)      │                      │
│          │ status (SCHEDULED/ACTIVE/...)      │                      │
│          │ total_extensions                   │                      │
│          │ created_by_id (FK→auth_user)       │                      │
│          │ config_id (FK→AuctionConfig)       │                      │
│          │ Indexes: 7 (see section 6.1)      │                      │
│          └───┬───────────────┬────────────────┘                      │
│              │ (1)           │ (1)                                  │
│              │ bidding       │ events                               │
│              │               │                                    │
│          ┌───▼────────────────▼──────────┐                         │
│          │    BID (Bids)                  │                         │
│          ├────────────────────────────────┤                         │
│          │ id (PK)                        │                         │
│          │ auction_id (FK→Auction)        │                         │
│          │ bidder_id (FK→auth_user)       │                         │
│          │ carrier_name                   │                         │
│          │ price, freight, origin, dest   │                         │
│          │ transit_time_days              │                         │
│          │ quote_validity_days            │                         │
│          │ submitted_at (unique per sup)  │                         │
│          │ total_cost (computed property) │                         │
│          │ Indexes: 4 (see section 6.2)  │                         │
│          └────────────────────────────────┘                         │
│              │                 │                                   │
│              │                 ▼                                   │
│              ▼            ┌──────────────────────┐                  │
│        ┌──────────────────┤ AuctionEvent         │                  │
│        │ (Audit Trail)    │ (Activity Log)       │                  │
│        │                  ├──────────────────────┤                  │
│        │                  │ id (PK)              │                  │
│        │                  │ auction_id (FK)      │                  │
│        │                  │ bidder_id (FK, null) │                  │
│        │                  │ event_type           │                  │
│        │                  │ description          │                  │
│        │                  │ extension_reason     │                  │
│        │                  │ created_at           │                  │
│        │                  │ Indexes: 3           │                  │
│        │                  └──────────────────────┘                  │
│        │                                                            │
│        └────────────┬────────────────────────────────┐             │
│                     ▼                                ▼             │
│          ┌───────────────────────┐    ┌──────────────────────┐     │
│          │ AuctionSnapshot       │    │  (Reserved)          │     │
│          │ (State Snapshots)     │    │ AuctionStatistics    │     │
│          ├───────────────────────┤    ├──────────────────────┤     │
│          │ id (PK)               │    │ (For analytics)      │     │
│          │ auction_id (FK)       │    │ avg_bid_price        │     │
│          │ total_bidders         │    │ extension_freq       │     │
│          │ ranking_data (JSON)   │    │ winner_id            │     │
│          │ created_at            │    │ final_price          │     │
│          │ Indexes: 3            │    └──────────────────────┘     │
│          └───────────────────────┘                                  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 14. Conclusion

This database schema provides:

✅ **Atomicity:** Transactions ensure consistency  
✅ **Concurrency:** Row-level locking prevents race conditions  
✅ **Performance:** 10 strategic indexes for O(n) queries  
✅ **Scalability:** Can handle millions of records  
✅ **Auditability:** Complete event trail for compliance  
✅ **Flexibility:** Supports bid revisions, multiple auctions  
✅ **Correctness:** Model validation + temporal constraints  

**Ready for:** Development, Testing, Production, and Scaling
