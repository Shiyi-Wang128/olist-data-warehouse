# Cleaning rules (ODS -> DWD / DIM)

Status: design only, nothing implemented. Decisions D1-D5, R14 extension and P01-P08 (now R19-R26) were accepted on 2026-11-03.
Counts come from `docs/data_profile.md` (Task 1) and `docs/metrics_log.md` sections "Task 2" and "Task 3"
(`src/explore/verify_issues.py`); all are real measurements on the raw CSVs.

## 0. Principles

- **ODS** is a typed copy of the raw CSVs (Parquet). No cleaning, no renaming; row counts must equal the CSVs.
- **DWD / DIM** flag rather than delete: add flag columns, keep every row. DWS / ADS filter on the flags.
  Exceptions are marked `exclude` / `dedupe` / `aggregate` below and apply only where a table cannot be built without them.
- Every rule is deterministic and re-runnable (idempotent overwrite of the target table).
- Action vocabulary: **flag** (add boolean column), **fill** (replace NULL), **dedupe**, **aggregate**, **exclude**
  (filter in a downstream layer, row stays in DWD), **rename**, **derive**, **cast**.

## 1. Rules decided

| ID | Target | Condition | Action | Affected rows | Rationale |
|---|---|---|---|---|---|
| R01 | `dim_customer`, `dwd_trade_order_item` (and any person-level metric) | every order | **derive** `customer_unique_id` by joining orders -> customers; person-level metrics (repurchase, retention) group by it, never by `customer_id` | 99,441 customer_id -> 96,096 persons; 2,997 persons (3.12%) have >1 order of any status (max 17); the final repurchase definition (R28 + R29: valid orders on >= 2 distinct dates) gives 2,065 of 94,990 (2.17%); 0 orders without a customer | Olist issues a new `customer_id` per order, so `customer_id` cannot identify a repeat buyer |
| R02 | `dwd_trade_order_item` (`is_gmv_order`), DWS/ADS GMV | `order_status IN ('canceled','unavailable')` | **flag** in DWD, **exclude** in DWS. GMV = `SUM(order_items.price)` by purchase date | 549 item rows (97,242.96 BRL = 0.72% of 13,591,643.70); only 1,234 orders carry these statuses and most have no item rows | GMV definition; keeping the rows lets us report excluded GMV |
| R03 | DWS freight metric | all items | Freight (`freight_value`) is its own metric, never added to GMV | 112,650 item rows; 383 with freight = 0 (kept, plausibly free shipping) | Keeps GMV comparable across categories |
| R04 | DWS order payment summary, reconciliation | orders having items and payments | **derive** `paid_amount = SUM(payment_value)` per order; reconciliation compares `paid_amount` with `SUM(price + freight_value)` in integer cents, tolerance **0.05 BRL** (D3) | 98,665 comparable orders: 98,089 exact, 273 off by 1 cent (rounding), 303 off by >= 2 cents, **260 off by > 5 cents (0.26%)** = orders that breach the tolerance. Aggregate difference +2,870.39 BRL (+0.018%) | Paid amount is auxiliary to GMV; see conflict C2 on why the comparison is against price + freight |
| R05 | ADS only | `purchase_date NOT BETWEEN '2017-01-01' AND '2018-08-31'` | **exclude** at ADS; DWD / DWS keep everything | Outside window: 371 item rows (370 before, 1 after), 349 of 99,441 orders (329 before, 20 after). In window after R02: 111,752 item rows, GMV 13,449,529.68 BRL | The first and last months of the dataset are sparse (2016: 329 orders; 2018-09/10: 20) |
| R06 | ADS retention (7d, 30d) | cohort day `d` with `d + N days > data_end`, **data_end = 2018-08-23** (D1) | **flag** `is_window_complete = false`; report as incomplete, never as low | With cohort date = first valid order (R28): 94,697 persons have a cohort date in 2017-01-01..2018-08-31. 7d: 1,761 incomplete (cohort date after 2018-08-16), 92,936 complete. 30d: 7,817 incomplete (after 2018-07-24), 86,880 complete. Cohort start uses the person's first valid order over the full history (293 persons first bought before 2017-01-01) | Order volume collapses after 2018-08-23, so later activity is missing, not absent |
| R07 | `dwd_trade_order` | `order_delivered_carrier_date < order_approved_at` | **flag** `is_ts_carrier_before_approval`; **flag only**, not excluded from any metric (D2) | 1,359 orders (1.37%). Verified: gap median 17.2 h (242 <= 1 h, 659 1h-1d, 444 1-7d, 14 > 7d); all 1,350 of them with a delivered date have delivered >= carrier | Business process (seller ships before payment approval clears); delivery time does not use `order_approved_at` |
| R08 | `dwd_trade_order` | `order_delivered_customer_date < order_delivered_carrier_date` | **flag** `is_ts_delivered_before_carrier` | 23 orders (gap 0.02 to 16.1 days, median 1.7) | Impossible sequence; at least one timestamp is wrong |
| R09 | `dwd_trade_order` | `order_status = 'delivered'` and `order_delivered_customer_date IS NULL` | **flag** `is_ts_delivered_no_date` | 8 orders | Status and timestamp disagree |
| R10 | `dwd_trade_order` | `order_status <> 'delivered'` and `order_delivered_customer_date IS NOT NULL` | **flag** `is_ts_nondelivered_has_date` | 6 orders | Status and timestamp disagree |
| R11 | DWS delivery-time metrics | `delivered`, has delivered date, and any of **R08-R10** flags (R07 is not an exclusion reason, D2) | **exclude** from delivery-time metrics (days from purchase / carrier to delivery, on-time rate) | Population: 96,470 delivered orders with a date; **eligible 96,447, excluded 23** (all R08; the R09 orders have no date and the R10 orders are not delivered, so they are outside the population anyway) | Flagged timestamps would distort the averages |
| R12 | `dim_product` | `product_category_name IS NULL` | **fill** `'unknown'` (and English `'unknown'`) | 610 products (1.85%) -> 1,603 item rows, 179,535.28 BRL (1.32% of price) | Keeps these items in GMV-by-category instead of dropping them in a join |
| R13 | `dim_product` category translation | category not in translation table | **fill** manual English names: `pc_gamer` -> `pc_gamer`, `portateis_cozinha_e_preparadores_de_alimentos` -> `portable_kitchen_and_food_preparers` (D5) | 13 products, 2 categories | Translation table has 71 rows; products use 73 distinct categories |
| R14 | `dwd_trade_review` (review rows), `dwd_trade_order` (order-level attributes) | grain `(review_id, order_id)`; several reviews per order | Keep all 99,224 review rows. **flag** `is_latest_review` = latest `review_answer_timestamp` per order (tie-break `review_creation_date`, then `review_id`). **derive** at order level `first_review_score` = score of the earliest review (earliest `review_creation_date`, tie-break `review_answer_timestamp`, then `review_id`); NULL if the order has no review. Order-level review attributes use rows with `is_latest_review`. Do **not** dedupe by `review_id` | 547 orders have >1 review: 551 rows get `is_latest_review = false`; 0 ties on the latest timestamp. `first_review_score` differs from the latest score in 188 of the 547 orders; the earliest `review_creation_date` is tied in 156 and fully resolved by `review_answer_timestamp` (0 ties left). `first_review_score` is NULL for 768 orders (no review). 789 `review_id`s span 2-3 orders (1,603 rows) | Part A: those 789 are one review applied to several orders of the same person (section 3), so `review_id` is not a key, `(review_id, order_id)` is. First score keeps the customer's initial sentiment next to the latest |
| R15 | `dim_geolocation` input | lat/lng outside lat -34..6, lng -74..-34 | **exclude** before aggregating (runs after the exact-duplicate drop of R16) | 42 raw rows, of which 33 remain after exact-duplicate removal; zip prefixes 19,015 -> 19,010 | Obvious wrong coordinates (outside Brazil) |
| R16 | `dim_geolocation` | exact duplicate rows, then (after R15) group by zip prefix | **dedupe** exact duplicate rows first (D4), then **aggregate** to one row per prefix: median `lat`, median `lng`, most frequent city and state (city normalized: lowercase, accents stripped; ties broken alphabetically) | Duplicates removed: 261,831 of 1,000,163 (-> 738,332); after R15 738,299 rows aggregate into 19,010 prefixes. Ties on most frequent normalized city: 38 prefixes (175 before normalization); 548 prefixes have >1 normalized city. Ties on state: 0; 8 prefixes have >1 state. Customer state equals the modal state for 99,162 of 99,162 matched customers | One row per prefix makes it joinable without fan-out; deduping first stops repeated records from weighting the median |
| R17 | all DWD / DIM tables with zip prefix | `zip_code_prefix < 10000` was stored as an integer | **cast** to string, left-pad with `'0'` to 5 characters | customers 23,995 rows; sellers 1,027; geolocation 245,733 | Leading zeros were lost on read; must be padded identically on both sides of every join |
| R18 | `dim_product` | columns `product_name_lenght`, `product_description_lenght` | **rename** to `product_name_length`, `product_description_length` | 2 columns (all 32,951 rows) | Misspelled in the source |
| R19 | `dwd_trade_order` | delivered but `order_delivered_carrier_date` / `order_approved_at` NULL | **flag** `is_ts_missing_carrier` / `is_ts_missing_approved` | 2 / 14 orders | Delivered orders should have both timestamps |
| R20 | `dwd_trade_payment` | `payment_value = 0`; `payment_type = 'not_defined'`; `payment_installments = 0`; order with no payment row | **flag** `is_zero_payment`, `is_type_undefined`, `is_zero_installments` on payment rows; **flag** `has_payment = false` on the order | 9; 3; 2 payment rows; 1 order | Suspicious values kept visible; paid amount (R04) still uses the values as recorded |
| R21 | `dim_customer` | one `customer_unique_id`, different zip/city/state across its orders | **dedupe** to one row per person, **SCD Type 1**: zip, city and state are overwritten with the values of the person's **latest order** (`order_purchase_timestamp`, tie-break `order_id`); no history, no effective dates | 96,096 output rows. 252 persons have changing attributes (250 in zip or state, 2 city only), overwriting 272 `customer_id` rows' attributes; 0 ties on the latest purchase timestamp | SCD1: simple and enough for person-level metrics. Trade-off: an old order is geographically attributed to where the person lives now; the original per-`customer_id` address stays available in ODS |
| R22 | `dwd_trade_order` | order has no item rows | **flag** `has_items = false` (they cannot appear in the item-grain fact table anyway) | 775 orders (603 unavailable, 164 canceled, 8 other) | Makes the gap between order count and item-fact order count explainable |
| R23 | `dim_product` | `product_weight_g = 0`; weight or dimensions NULL | **flag** `is_weight_zero`, `is_dim_missing`; keep the value | 4; 2 products | Zero weight is not a real measurement |
| R24 | `dim_seller` | `seller_city` contains digits or `/ @ \` | **flag** `is_city_dirty`; no rewrite | 18 sellers (0.58%) | Free text typed by sellers; rewriting would guess |
| R25 | `dim_customer`, `dim_seller` | zip prefix missing from `dim_geolocation` (after R15, R16) | **flag** `has_geo = false`; join with LEFT JOIN | 279 customers (278 before R15), 7 sellers | Geo attributes are optional, missing ones must not drop rows |
| R26 | `dwd_trade_order_item` (`is_gmv_undelivered`), DWS GMV | order status approved / invoiced / processing / shipped (not delivered, not excluded by R02) | **flag**; keep in GMV as defined by R02, report the split | 1,721 orders, 1,904 item rows (3 approved, 359 invoiced, 357 processing, 1,185 shipped), 272,902.63 BRL (2.01% of GMV) | GMV scope stays as decided; the split shows how much of it is not yet delivered |
| R27 | DWS daily tables, ADS daily GMV | `purchase_date` between 2018-08-24 and 2018-08-31 | **flag** `is_partial_day = true`; the days stay in GMV (D1) | 8 days: 356 orders with items, 406 item rows (405 after R02), GMV 38,821.69 BRL (0.29% of in-window GMV). 371 orders in total (typical ~266 per day, so ~2,100 expected) | Order volume collapses after 2018-08-23, so these days look like a drop that is not real |
| R28 | `dwd_trade_order` (`is_valid_order`), DWS person-level cohort table, ADS repurchase and retention | `order_status NOT IN ('canceled','unavailable')` = the same predicate as R02 (one shared definition) | **flag** `is_valid_order` in DWD. Only valid orders count, both for the first purchase and for return purchases. **cohort date** = date of the person's first valid order. Persons with no valid order are **excluded** from cohorts (DWS). What counts as a repurchase or return is defined in R29 | Persons: 96,096 -> **94,990** with >=1 valid order; **1,106 excluded entirely** (536 only canceled, 570 only unavailable; 1,115 orders). 1,153 persons have a canceled/unavailable earliest order: 1,106 of them are the excluded ones, 47 have a later valid order, and for **31 the cohort date actually changes** (the other 16 have a valid order on the same day; median shift 48 days, max 493). Cohorts in the ADS window: 95,764 -> 94,697. Persons with >1 valid order: 2,888 of 94,990 (3.04%), before the date rule of R29; 109 persons of the original 2,997 drop out because their extra orders were canceled/unavailable. Max valid orders per person 16 | A cancelled order is not a purchase; retention and repurchase must use the same scope as GMV (R02) so the metrics reconcile |

| R29 | DWS person-level purchase-occasion table, ADS repurchase rate and retention | valid orders only (R28), grouped by `customer_unique_id` and `purchase_date` (calendar date of `order_purchase_timestamp`) | **derive** purchase occasions: all valid orders of a person on the same date are **one occasion**. **Repurchase** = a person with valid orders on **>= 2 distinct purchase dates**. **Retention**: `day_offset = purchase_date - cohort_date` (R28); day 0 is never a return; a return is a valid order on day 1..N (N = 7 or 30), and a person is retained at N if there is at least one return in day 1..N | Repurchasers: **2,065 of 94,990 = 2.17%** (2,054 of the 94,697 cohorts in the ADS window = 2.17%; 11 more repurchasers have a cohort date before the window). Chain: 2,997 (3.12% of 96,096, all orders) -> 2,888 (3.04%, valid orders) -> **2,065** (2.17%, distinct dates). 823 persons have several valid orders but all on one date. Distinct purchase dates per person: 1 date 92,925; 2 dates 1,909; 3 dates 124; 4+ dates 32 (max 16); 2,287 extra purchase occasions in total. First return at day offset 1 / 2-7 / 8-30 / >30: 46 / 167 / 402 / 1,450 persons (not a retention rate: includes incomplete cohorts) | Same-day orders are typically one basket split into several orders, not a new decision to buy; day 0 is the acquisition day, so only a later date shows the customer coming back |

## 2. Rules proposed (not yet decided)

None. P01-P08 were accepted and promoted: P01 -> R19, P02 -> R20, P03 -> R21, P04 -> R22, P05 -> R23, P06 -> R24,
P07 -> R25, P08 -> R26.

## 3. Part A verification summary

- **Reviews (789 review_ids linked to >1 order)**: score, title, message, creation date and answer timestamp are identical in
  789 of 789 groups; the linked orders belong to the same `customer_unique_id` in 789 of 789; 730 groups were purchased
  within 1 minute of each other (254 at the same second), 18 within 1 hour, 1 within 1-7 days and 40 more than 7 days apart
  (max 127 days). Conclusion: one review submission applied to several orders of the same person, mostly an order split or a
  multi-order checkout. It is business behavior, not a data error, so rows must not be deleted by `review_id`.
- **Payments vs items**: 380 in Task 1 was float-rounding noise. In exact cents 303 orders (0.31%) differ by >= 2 cents,
  plus 273 that differ by exactly 1 cent (rounding on 2+ item orders). Of the 303, 264 paid more (249 of them with
  installments > 1; median overpay 9.4% of the items total), which matches installment interest. The 39 that paid less are
  mostly small (median -0.04 BRL, a few up to -51.62 BRL), likely rounding of installment splits and some discounts.
  Vouchers are not a cause (0.19% mismatch rate with vouchers vs 0.31% without).

## 4. Conflicts between the decisions and the data (history)

- **C1 - ADS end date and retention window.** Daily orders fall from a typical ~266 to 144 on 2018-08-23, then 99, 69, 73,
  67, 44, 14, 4, 1 up to 2018-08-31 (371 orders in 8 days vs ~2,100 expected). Daily GMV for 2018-08-24..31 would look like
  a collapse and cohorts there like zero retention. The latest purchase date, 2018-10-17, is a handful of stray orders, so
  "observation end" must not be taken as `MAX(purchase date)`. **Resolved by D1:** `data_end` = 2018-08-23 (R06), the
  partial days stay in GMV and are flagged (R27).
- **C2 - GMV vs paid reconciliation.** GMV is `SUM(price)` but payments include freight: payment equals price only for 338 of
  98,665 orders. **Resolved:** the reconciliation compares paid amount with `price + freight_value` (R04, tolerance 0.05 BRL, D3).
- **C3 - R07 excluded from delivery-time metrics.** Delivery time does not use `order_approved_at`, and all 1,350 of those
  orders with a delivered date have a sane delivery sequence; excluding R07 would drop 1,350 valid orders (1.4%).
  **Resolved by D2:** R07 is flag-only; eligible population 96,447 instead of 95,097.
- **C4 - Task 1 figure corrected.** "380 orders with mismatching payment" was float noise; the correct count is 303 (>= 2 cents).

## 5. Open decisions

None.

Resolved decisions (2026-11-03 and later):

| ID | Decision | Applied in |
|---|---|---|
| D1 | `data_end` = 2018-08-23 for retention; 2018-08-24..31 stay in GMV and are flagged partial | R06, R27 |
| D2 | R07 flag-only; delivery-time metrics exclude only R08-R10 | R07, R11 |
| D3 | Reconciliation tolerance 0.05 BRL | R04 |
| D4 | Drop exact duplicate geolocation rows first, then aggregate with medians | R16 (R15 order) |
| D5 | Accept `pc_gamer` and `portable_kitchen_and_food_preparers` | R13 |
| R14 | Keep `is_latest_review`, add order-level `first_review_score` | R14 |
| P01-P08 | Accepted; P03 is SCD Type 1 | R19-R26 (R21 = SCD1) |
| D6 | Retention and repurchase count only orders not in (canceled, unavailable), for cohort date and return purchases; persons with no valid order leave the cohorts; same scope as R02 | R28 (R06 recounted) |
| D7 | Repurchase = valid orders on >= 2 distinct purchase dates; same-date orders are one purchase occasion; retention: day 0 never a return, returns are valid orders on day 1..N | R29 |

## 6. Rules that become automated data quality checks

Severity: **block** = failure stops downstream tasks in the Airflow DAG; **warn** = logged, does not block.

| Check | Rule(s) | Severity |
|---|---|---|
| ODS row counts equal raw CSV row counts (9 tables) | ODS principle | block |
| DWD row count equals ODS row count per table (nothing deleted); `dim_customer` (R21) and `dim_geolocation` (R16) are aggregated and checked against their own expected counts (96,096 and 19,010) | flag principle, R16, R21 | block |
| Unique keys: `order_id`, `customer_id`, `(order_id, order_item_id)`, `product_id`, `seller_id`, `(review_id, order_id)`, one row per `customer_unique_id` in `dim_customer`, one row per zip in `dim_geolocation` | R14, R16, R21 | block |
| Foreign keys: items -> orders / products / sellers, orders -> customers, payments -> orders, reviews -> orders (all 0 orphans today) | profile 3.6 | block |
| Not null: `order_id`, `customer_unique_id`, `order_purchase_timestamp`, `price`, `category` after fill | R01, R12 | block |
| Accepted values: `order_status` in the 8 known values, `review_score` 1-5, `payment_type` in the 5 known values | profile | block (`not_defined` only warn) |
| Range: `price > 0`, `freight_value >= 0` (0 violations today) | profile 3.7 | block |
| Every product category has an English name | R12, R13 | block |
| Zip prefix matches `^\d{5}$` in every DWD / DIM table | R17 | block |
| `dim_geolocation` coordinates inside the Brazil bounding box | R15 | block |
| Exactly one `is_latest_review` row per order with a review; `first_review_score` NULL only for orders without a review (768 today) | R14 | block |
| Flag shares stay near baseline (R07 1.37%, R08-R10 <= 0.05%, R19-R25 counts as listed above) | R07-R10, R19-R25 | warn |
| Per-order reconciliation: orders with `abs(paid - (price + freight)) > 0.05` stay below 1% (today 0.26%) | R04 | warn |
| Aggregate reconciliation: `abs(SUM(paid) - SUM(price + freight)) / SUM(price + freight) <= 0.1%` (today 0.018%) | R04 | block |
| GMV cross-layer: DWS total equals `SUM(price)` over non-excluded statuses in the ADS window | R02, R05 | block |
| `is_partial_day` is true exactly for purchase dates 2018-08-24..31 | R27 | block |
| No retention cohort marked complete when `cohort_day + N > data_end` (2018-08-23) | R06 | block |
| Purchase-occasion table: one row per (person, purchase date) with valid orders; repurchasers = persons with >= 2 occasions (2,065 today); no retention return has `day_offset < 1` | R29 | block |
| Cohort table: one row per person with a valid order (94,990 today); cohort date equals the minimum purchase date over valid orders; no person with only canceled/unavailable orders; `is_valid_order` uses the same predicate as `is_gmv_order` (R02) | R28, R02 | block |
| Delivery-time metric population equals the eligible count (96,447 today) | R11 | warn |

## 7. Known limitations

- **Midnight edge case (R29).** A purchase date is the calendar date of `order_purchase_timestamp`, with no time-zone
  conversion and no tolerance window. Two valid orders placed a few minutes apart but on either side of midnight count as two
  purchase occasions, so that person counts as a repurchaser and as a day-1 return. Measured impact: 25 of 2,065 repurchasers
  (1.2%; 0.03% of all 94,990 persons) have every valid order inside a window shorter than 24 h, 1 inside 6 h and none inside
  1 h; the gap between the last order on the cohort day and the first order on a later date is under 24 h for 29 persons,
  under 6 h for 1 and under 1 h for 0. The effect is accepted: it is small and the date rule stays simple and reproducible.
- **Purchase date vs window.** The ADS date window (R05), the partial days (R27) and the cohort day all use the same
  purchase date; none of them is shifted for time zones.
