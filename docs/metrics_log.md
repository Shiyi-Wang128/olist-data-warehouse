# Metrics log

Real measurements only. Source of truth for resume / README numbers.

## Task 1: raw data profiling (2026-10-25)

Script: `src/explore/profile_raw.py` (pandas 2.3.3, Python 3.9.12). Full report: `docs/data_profile.md`.

### Row counts (raw, before any cleaning)
| table | rows |
|---|---|
| customers | 99,441 |
| geolocation | 1,000,163 |
| orders | 99,441 |
| order_items | 112,650 |
| payments | 103,886 |
| reviews | 99,224 |
| products | 32,951 |
| sellers | 3,095 |
| translation | 71 |

Order purchase range: 2016-09-04 -> 2018-10-17.

### Dirty-data findings (candidate cleaning rules; counts are affected rows)
| issue | rows |
|---|---|
| distinct customer_id / customer_unique_id | 99,441 / 96,096 |
| persons with >1 order (of 96,096) | 2,997 (3.12%) |
| status='delivered' but delivered_customer_date NULL | 8 |
| status='delivered' but carrier date NULL / approved_at NULL | 2 / 14 |
| status!='delivered' but delivered_customer_date NOT NULL | 6 |
| carrier date earlier than approved_at | 1,359 |
| customer delivery earlier than carrier handover | 23 |
| orders canceled / unavailable | 625 / 609 |
| orders with no order_items | 775 (603 unavailable, 164 canceled, 8 other) |
| orders with no payments | 1 |
| products with NULL category | 610 (1.85%) -> 1,603 order_items rows |
| products whose category has no English translation | 13 (2 categories: pc_gamer, portateis_cozinha_e_preparadores_de_alimentos) |
| products with NULL weight/dimensions | 2; weight == 0: 4 |
| reviews: rows with duplicated review_id | 1,603 (789 ids, 814 extra rows; 0 fully identical rows) |
| reviews: orders with >1 review | 547 |
| geolocation: fully duplicated rows (extra beyond first) | 261,831 (26.18%) |
| geolocation: zip prefixes with >1 distinct (lat,lng) | 17,781 of 19,015 |
| geolocation: coordinates outside Brazil bounding box | 42 |
| customer / seller zip prefixes absent from geolocation | 278 / 7 |
| foreign-key orphans (all 6 child->parent checks) | 0 |
| orders where sum(price+freight) differs from sum(payment_value) by >= 2 cents | 303 (corrected in Task 2; the original 380 was float-rounding noise) |
| payments value == 0 / type 'not_defined' | 9 / 3 |
| seller_city with digits or slash/@ | 18 |
| customer_unique_id with differing zip/state across customer_ids | 250 |

### Data quality rules
Not implemented yet (profiling only): 0 rules, 0 runs blocked.

## Task 2: verification of open questions (2026-11-02)

Script: `src/explore/verify_issues.py` (read-only, prints to stdout). Amounts compared in integer cents.

### A1. Reviews linked to >1 order
| metric | value |
|---|---|
| review_ids linked to >1 order_id | 789 (764 link 2 orders, 25 link 3 orders); 1,603 rows |
| identical score / title / message / creation date / answer timestamp across rows | 789 / 789 (100%) each |
| linked orders belong to the same customer_unique_id | 789 / 789 (100%) |
| purchase-time gap between linked orders: 0s / 1s-1min / 1min-1h / 1h-1d / 1d-7d / >7d | 254 / 476 / 18 / 0 / 1 / 40 (median 1s, max 127.1 days) |
| orders with >1 review | 547 (551 extra rows); latest answer_timestamp tied: 0; scores differ within the order: 202 |

Conclusion: one review submission applied to several orders of the same person (business behavior, not a data error).

### A2. Payments vs items (exact cents, 98,665 orders having both items and payments)
| metric | value |
|---|---|
| exact match | 98,089 |
| off by exactly 1 cent (rounding noise; 209 are orders with 3+ items, 64 with 2 items) | 273 |
| off by >= 2 cents | 303 (0.31%); > 5 cents: 260 |
| direction of the 303 | paid MORE 264 (87%), paid LESS 39 |
| paid MORE with installments > 1 | 249 of 264 (94%); median overpay 9.4% of items total (p25 5.8%, p75 13.0%) |
| mismatch rate installments > 1 vs = 1 | 0.53% (269 / 50,840) vs 0.07% (34 / 47,825) |
| mismatch rate with voucher vs without | 0.19% (7 / 3,766) vs 0.31% (296 / 94,899) -> voucher is not the cause |
| paid LESS: median / p25 of difference | -0.04 BRL / -7.58 BRL (min -51.62) |
| aggregate: sum(payment_value) vs sum(price+freight) | 15,846,280.17 vs 15,843,409.78 BRL (+0.018%) |
| orders where payment == price only (freight excluded) | 338 of 98,665 |

### C. Checks on cleaning decisions
| metric | value |
|---|---|
| order_items rows in canceled/unavailable orders (excluded from GMV) | 549 rows, 97,242.96 BRL of 13,591,643.70 (0.72%) |
| items in non-delivered, non-excluded statuses (still counted in GMV) | 1,721 orders, 272,902.63 BRL (2.01%) |
| order_items rows in 2017-01-01..2018-08-31 / outside | 112,279 / 371 (370 before, 1 after); orders in range 99,092 of 99,441 |
| GMV in range after status exclusion | 13,449,529.68 BRL, 111,752 item rows |
| daily orders at the data tail (2018-08-22 .. 08-31) | 187, 144, 99, 69, 73, 67, 44, 14, 4, 1 (prior-28-day median ~266); last day >= 50% of that median: 2018-08-23 |
| persons whose first purchase is before 2017-01-01 | 326 |
| timestamp flags: carrier<approved / delivered<carrier / delivered w/o date / non-delivered with date | 1,359 / 23 / 8 / 6 (no overlap, 1,396 total) |
| carrier<approved: gap <=1h / 1h-1d / 1d-7d / >7d; median | 242 / 659 / 444 / 14; 17.2h; all 1,350 with a delivered date have delivered >= carrier |
| delivery-time eligible orders (delivered, has date) | 96,470; excluding all 4 flags: 95,097; excluding only the 3 other flags: 96,447 |
| NULL-category items | 1,603 rows, 179,535.28 BRL (1.32% of price) |
| geolocation after bounding-box drop | 42 rows dropped; zip prefixes 19,015 -> 19,010; customer rows without coordinates 278 -> 279; sellers 7 -> 7 |
| zip prefix: most frequent city tied / most frequent state tied / prefixes with >1 state | 175 / 0 / 8 (of 19,010) |
| customer_state equals geolocation modal state | 99,162 of 99,162 matched customers |
| zip prefixes needing zero-padding (< 10000) | customers 23,995 rows; sellers 1,027; geolocation 245,733 |

### Data quality rules
Not implemented yet: 0 rules running, 0 runs blocked. Planned list in `docs/cleaning_rules.md`.

## Task 3: cleaning-rule decisions applied (2026-11-03)

Script: `src/explore/verify_issues.py` Part D (read-only). Rules and decisions: `docs/cleaning_rules.md` (R01-R27).

### Counts that changed or were newly measured
| metric | value |
|---|---|
| D1: persons with first purchase in 2017-01-01..2018-08-31 | 95,764 |
| D1: 7d retention cohorts with data_end = 2018-08-23 | 1,778 persons incomplete (first purchase after 2018-08-16), 93,986 complete |
| D1: 30d retention cohorts with data_end = 2018-08-23 | 7,900 persons incomplete (first purchase after 2018-07-24), 87,864 complete |
| D1: partial days 2018-08-24..31 | 356 orders with items, 406 item rows (405 after status exclusion), GMV 38,821.69 BRL; 371 orders in total |
| D2: delivery-time population (excluding only delivered<carrier, delivered w/o date, non-delivered with date) | 96,470 delivered with date; 96,447 eligible; 23 excluded (was 95,097 / 1,373 when R07 was excluded) |
| D3: reconciliation tolerance 0.05 BRL | 260 orders breach (0.26% of 98,665) |
| D4: geolocation exact duplicates removed first | 261,831 removed -> 738,332 rows; bounding box then drops 33 (42 on raw rows) -> 738,299 rows -> 19,010 zip prefixes |
| D4: ties on most frequent city after normalization (lowercase, no accents) | 38 prefixes (175 before normalization); 548 prefixes with >1 normalized city; state ties 0, prefixes with >1 state 8 |
| D4: customer state vs modal state; customers / sellers without coordinates | 0 mismatches of 99,162; 279 / 7 |
| R14: orders with a review / without | 98,673 / 768 |
| R14: orders with >1 review where first score != latest score | 188 of 547 (156 orders tied on earliest creation date, 0 ties left after answer timestamp) |
| R21 (P03, SCD Type 1): persons with changing zip/city/state | 252 (250 zip or state, 2 city only); 272 customer_id rows overwritten; 0 ties on latest purchase timestamp; dim_customer 96,096 rows |
| R26 (P08): items in approved/invoiced/processing/shipped orders | 1,904 item rows, 1,721 orders, 272,902.63 BRL |

### Data quality rules
27 cleaning rules documented (R01-R27); 18 automated checks planned in `docs/cleaning_rules.md` section 6 (15 block, 3 warn). Implemented: 0, blocked runs: 0.

## Task 4: D6 decision, valid-order scope for cohorts and repurchase (2026-11-03)

Script: `src/explore/verify_issues.py` Part E (read-only). Rule: `docs/cleaning_rules.md` R28. Valid order = status not in (canceled, unavailable), same predicate as R02.
These numbers supersede the all-orders cohort counts in the Task 3 section above.

| metric | value |
|---|---|
| persons (customer_unique_id) / with >=1 valid order / excluded entirely | 96,096 / 94,990 / 1,106 (536 only canceled, 570 only unavailable; 1,115 orders) |
| persons whose earliest order is canceled/unavailable | 1,153 (1,106 excluded entirely, 47 have a later valid order) |
| persons whose cohort DATE changes | 31 (median shift 48 days, p90 283, max 493); the other 16 of the 47 have a valid order on the same day |
| cohorts with date in 2017-01-01..2018-08-31 | 95,764 (all orders) -> 94,697 (valid orders); no person crosses the window edge |
| persons whose first valid order is before 2017-01-01 | 293 (was 326 with all orders) |
| repurchase: persons with >1 valid order | 2,888 of 94,990 = 3.04% (was 2,997 of 96,096 = 3.12%); 109 persons lose repeat status; max valid orders 16 |
| repurchase on >= 2 distinct purchase dates (information for open decision D7) | 2,065 = 2.17% |
| 7d retention cohorts with data_end = 2018-08-23 | 1,761 incomplete, 92,936 complete |
| 30d retention cohorts with data_end = 2018-08-23 | 7,817 incomplete, 86,880 complete |

### Data quality rules
28 cleaning rules documented (R01-R28); 19 automated checks planned (16 block, 3 warn). Implemented: 0, blocked runs: 0.

## Task 5: D7 decision, repurchase = valid orders on >= 2 distinct purchase dates (2026-11-03)

Script: `src/explore/verify_issues.py` Part F (read-only). Rule: `docs/cleaning_rules.md` R29. Scope: D6 valid orders (R28).
Final repurchase numbers (D6 + D7):

| metric | value |
|---|---|
| persons with a valid order | 94,990 |
| **repurchasers (valid orders on >= 2 distinct purchase dates)** | **2,065 = 2.17%** |
| chain: all orders >1 order -> valid orders >1 order -> >= 2 distinct dates | 2,997 (3.12% of 96,096) -> 2,888 (3.04% of 94,990) -> 2,065 (2.17%) |
| persons with several valid orders, all on one date (one occasion) | 823 |
| persons by distinct purchase dates: 1 / 2 / 3 / 4+ | 92,925 / 1,909 / 124 / 32 (max 16); 2,287 extra occasions |
| repurchasers among the 94,697 cohorts in the ADS window | 2,054 = 2.17% (11 more repurchasers have a cohort date before 2017-01-01, 0 after 2018-08-31) |
| first return at day offset 1 / 2-7 / 8-30 / >30 | 46 / 167 / 402 / 1,450 persons (all cohorts, not a retention rate) |
| midnight edge case: repurchasers with all valid orders within < 1h / < 6h / < 24h | 0 / 1 / 25 persons (1.2% of repurchasers) |
| midnight edge case: gap between last order on cohort day and first order on a later date < 1h / < 6h / < 24h | 0 / 1 / 29 of 2,065 |

### Data quality rules
29 cleaning rules documented (R01-R29); 20 automated checks planned (17 block, 3 warn). Implemented: 0, blocked runs: 0.
