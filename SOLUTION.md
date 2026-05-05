1. Optimization Approach
1.1 Query Optimization
a. Database Indexing

Indexes were added on frequently queried fields:

CREATE INDEX idx_profiles_gender ON profiles(gender);
CREATE INDEX idx_profiles_country_id ON profiles(country_id);
CREATE INDEX idx_profiles_age_group ON profiles(age_group);
CREATE INDEX idx_profiles_age ON profiles(age);
CREATE INDEX idx_profiles_gender_country ON profiles(gender, country_id);


Reasoning:
Queries frequently filter on gender, country_id, and age
Composite index (gender, country_id) optimizes the most common combined query
Reduces full table scans

b. Query-Level Pagination
Pagination is applied directly at the database level:
queryset.offset((page - 1) * limit).limit(limit)

Reasoning:
Avoids loading entire datasets into memory
Ensures only required rows are transferred
Maintains low latency even at large scale

c. Sorting Optimization
Sorting is applied at the database level using indexed fields:
queryset.order_by(order_str)

Reasoning:
Avoids in-memory sorting
Uses database index ordering when available

1.2 Caching Strategy (LRU + TTL)
An in-memory cache was implemented with:
TTL (Time-To-Live): 5 minutes
LRU (Least Recently Used): eviction when max size is reached

Cache Flow:
Normalize query parameters into a deterministic key
Check cache before querying database
Store results after DB query
Invalidate cache on writes

Key Implementation:
cache_store = {}
MAX_CACHE_SIZE = 1000
CACHE_TTL = 300

Why TTL + LRU:
TTL ensures stale data is automatically removed
LRU ensures memory is bounded under load

1.3 Cache Key Normalization
normalize_cache_key(filters, page, limit, sort_by, order)

Ensures:
gender=male&country=NG == country=NG&gender=male
Prevents duplicate cache entries for same logical query

1.4 Ingestion Optimization
a. Chunked Processing
CHUNK_SIZE = 1000
Rows are processed in batches
Reduces memory overhead
Improves DB insertion efficiency

b. Bulk Insert with Fallback
await Profile.bulk_create(batch, ignore_conflicts=True)
Fallback to row-by-row insert if bulk fails.

c. Preloaded Duplicate Detection
existing_names = set(await Profile.all().values_list("name", flat=True))
Avoids per-row DB queries
O(1) duplicate checks

2. Design Decisions & Trade-offs
2.1 Monolithic Architecture
Decision:
Single backend service

Pros:
Simpler to develop and deploy
Lower latency (no inter-service calls)

Cons:
Cannot scale components independently

2.2 In-Memory Cache (LRU + TTL) vs Redis
Decision:
Use in-memory cache for this stage

Pros:
Fast to implement
No external dependencies

Cons:
Not shared across instances
Breaks under horizontal scaling

2.3 TTL-Based Caching (5 minutes)
Decision:
Cache results for 5 minutes

Pros:
Reduces DB load significantly
Acceptable staleness for analytics

Cons:
Data may be temporarily outdated although for a few minutes

2.4 Cache Invalidation Strategy
Decision:
Invalidate entire cache on writes
invalidate_all()

Pros:
Simple and correct
Guarantees no stale reads

Cons:
Less efficient than selective invalidation

2.5 Indexing Trade-off
Pros:
Fast queries
Scales to millions of rows

Cons:
Slower writes
Increased storage usage

Justification:
System is read-heavy, trade-off is acceptable

3. Query Performance Comparison

| Scenario | Without Optimization | With Optimization |
|----------|----------------------|-------------------|
| Filter by gender | ~850ms | ~86ms |
| Filter by gender + country | ~1214ms | ~150ms |
| Cached query (repeat) | ~870ms | ~5–13ms |
| Paginated query (page 1) | ~900ms | ~100ms |

Observations:
Indexing reduces query time by ~10x
Caching reduces repeated query time by ~100x
Pagination prevents large data transfers

4. Ingestion Failures & Edge Case Handling

4.1 Row-Level Fault Tolerance
Invalid rows are skipped, not fatal
Processing continues for valid rows

4.2 Validation Rules
Handled in _validate_row():

Missing fields
Invalid gender
Invalid age
Invalid probabilities
Malformed rows

4.3 Duplicate Handling
Two layers:

Existing DB records
Intra-file duplicates
if name in existing_names or name in seen_in_file:

4.4 Batch Failure Recovery
If bulk insert fails:

Fallback to individual inserts
Prevents losing entire batch

4.5 Encoding Handling
try:
    decoded = content.decode("utf-8")
except UnicodeDecodeError:
    decoded = content.decode("latin-1")
Supports multiple encodings

4.6 Error Reporting

Response includes:

{
  "inserted": X,
  "skipped": Y,
  "reasons": {
    "invalid_age": 10,
    "duplicate_name": 5
  }
}
Clear visibility into ingestion issues