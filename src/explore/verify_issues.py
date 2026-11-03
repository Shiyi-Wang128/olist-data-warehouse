"""Verify open questions from data profiling (read-only on data/raw/).

Part A1: reviews whose review_id links to >1 order_id
Part A2: orders where sum(price+freight) != sum(payment_value)
Part C : numbers needed to check the cleaning-rule decisions against the data

Run: python src/explore/verify_issues.py   (prints to stdout only)
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8")
pd.set_option("display.width", 200)
pd.set_option("display.max_columns", 30)

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
ORDER_TS = ["order_purchase_timestamp", "order_approved_at", "order_delivered_carrier_date",
            "order_delivered_customer_date", "order_estimated_delivery_date"]

c = pd.read_csv(RAW / "olist_customers_dataset.csv")
s = pd.read_csv(RAW / "olist_sellers_dataset.csv")
g = pd.read_csv(RAW / "olist_geolocation_dataset.csv")
o = pd.read_csv(RAW / "olist_orders_dataset.csv", parse_dates=ORDER_TS)
oi = pd.read_csv(RAW / "olist_order_items_dataset.csv")
p = pd.read_csv(RAW / "olist_order_payments_dataset.csv")
r = pd.read_csv(RAW / "olist_order_reviews_dataset.csv",
                parse_dates=["review_creation_date", "review_answer_timestamp"])


def h(title):
    print(f"\n{'=' * 8} {title} {'=' * 8}")


def cut_secs(secs, bins, labels):
    return pd.cut(secs, bins=bins, labels=labels).value_counts().reindex(labels)


# ---------------------------------------------------------------- A1
h("A1. Reviews: review_id linked to >1 order_id")
n_orders = r.groupby("review_id")["order_id"].nunique()
ids = n_orders[n_orders > 1].index
print(f"review_ids linked to >1 order: {len(ids)}; rows involved: {r['review_id'].isin(ids).sum()}")
print("orders per such review_id:")
print(n_orders[ids].value_counts().sort_index().to_string())

m = (r[r["review_id"].isin(ids)]
     .merge(o[["order_id", "customer_id", "order_purchase_timestamp"]], on="order_id", how="left")
     .merge(c[["customer_id", "customer_unique_id"]], on="customer_id", how="left"))
grp = m.groupby("review_id")
summ = pd.DataFrame({
    "n_score": grp["review_score"].nunique(dropna=False),
    "n_title": grp["review_comment_title"].nunique(dropna=False),
    "n_message": grp["review_comment_message"].nunique(dropna=False),
    "n_created": grp["review_creation_date"].nunique(dropna=False),
    "n_answered": grp["review_answer_timestamp"].nunique(dropna=False),
    "n_person": grp["customer_unique_id"].nunique(dropna=False),
    "gap": grp["order_purchase_timestamp"].max() - grp["order_purchase_timestamp"].min(),
})
total = len(summ)
for col, label in [("n_score", "identical review_score"), ("n_title", "identical comment title"),
                   ("n_message", "identical comment message"), ("n_created", "identical creation date"),
                   ("n_answered", "identical answer timestamp"), ("n_person", "same customer_unique_id")]:
    k = int((summ[col] == 1).sum())
    print(f"{label}: {k} / {total} ({k / total * 100:.1f}%)")
allsame = ((summ[["n_score", "n_title", "n_message", "n_created", "n_answered"]] == 1).all(axis=1))
print(f"ALL content+timestamps identical: {int(allsame.sum())} / {total}")
print(f"ALL content identical AND same person: {int((allsame & (summ['n_person'] == 1)).sum())} / {total}")
print("\npurchase-time gap between linked orders (max-min per review_id):")
secs = summ["gap"].dt.total_seconds()
labels = ["0s", "1s-1min", "1min-1h", "1h-1d", "1d-7d", ">7d"]
print(cut_secs(secs, [-1, 0, 60, 3600, 86400, 7 * 86400, np.inf], labels).to_string())
print(f"median gap (s): {secs.median():.0f}; p90 (s): {secs.quantile(.9):.0f}; max (days): {secs.max() / 86400:.1f}")
print("\ndifferent-person groups, example:")
print(summ[summ["n_person"] > 1].head(5).to_string())

# ---------------------------------------------------------------- A2
h("A2. Payments vs items: orders where sum(price+freight) != sum(payment_value)")
items = oi.groupby("order_id").agg(price=("price", "sum"), freight=("freight_value", "sum"), n_items=("order_item_id", "size"))
items["items_total"] = items["price"] + items["freight"]
p["is_voucher"] = p["payment_type"].eq("voucher")
p["is_credit"] = p["payment_type"].eq("credit_card")
pay = p.groupby("order_id").agg(paid=("payment_value", "sum"), n_pay=("payment_sequential", "size"),
                                max_inst=("payment_installments", "max"),
                                has_voucher=("is_voucher", "max"), has_credit=("is_credit", "max"))
pay["types"] = p.groupby("order_id")["payment_type"].agg(lambda x: "+".join(sorted(set(x))))
cmp_ = items.join(pay, how="inner").join(o.set_index("order_id")["order_status"])
cmp_["diff"] = cmp_["paid"] - cmp_["items_total"]
cmp_["mism"] = cmp_["diff"].abs() > 0.01
cmp_["direction"] = np.where(cmp_["diff"] > 0.01, "paid MORE", np.where(cmp_["diff"] < -0.01, "paid LESS", "match"))
cmp_["inst_gt1"] = cmp_["max_inst"] > 1
mm = cmp_[cmp_["mism"]]
print(f"orders with items and payments: {len(cmp_)}; mismatching: {len(mm)} ({len(mm) / len(cmp_) * 100:.2f}%)")
print("\ndirection:")
print(cmp_["direction"].value_counts().to_string())
print("\ndiff (paid - items_total) summary, mismatching orders only:")
print(mm.groupby("direction")["diff"].describe().to_string())
print("\n|diff| buckets (BRL):")
labels = ["<=1", "1-5", "5-20", "20-100", ">100"]
print(cut_secs(mm["diff"].abs(), [0.01, 1, 5, 20, 100, np.inf], labels).to_string())
more = mm[mm["direction"] == "paid MORE"]
less = mm[mm["direction"] == "paid LESS"]
print("\nrelative overpay (paid/items_total - 1) for 'paid MORE' quantiles:")
print((more["paid"] / more["items_total"] - 1).quantile([.1, .25, .5, .75, .9]).round(4).to_string())

print("\nmismatch rate by installments (all orders with items+payments):")
print(cmp_.groupby("inst_gt1")["mism"].agg(orders="size", mismatches="sum", rate="mean").to_string())
print("\ndirection x installments (mismatching orders):")
print(pd.crosstab(mm["direction"], mm["inst_gt1"].map({True: "installments>1", False: "installments=1"})).to_string())
print("\nmismatch rate by voucher presence:")
print(cmp_.groupby("has_voucher")["mism"].agg(orders="size", mismatches="sum", rate="mean").to_string())
print("\ndirection x voucher (mismatching orders):")
print(pd.crosstab(mm["direction"], mm["has_voucher"].map({True: "has voucher", False: "no voucher"})).to_string())
print("\nmismatch rate by number of payment rows:")
cmp_["pay_rows"] = cmp_["n_pay"].clip(upper=3).map({1: "1", 2: "2", 3: "3+"})
print(cmp_.groupby("pay_rows")["mism"].agg(orders="size", mismatches="sum", rate="mean").to_string())
print("\nmismatching orders by payment-type combination (top 8):")
print(pd.crosstab(mm["types"], mm["direction"]).assign(total=lambda d: d.sum(axis=1)).sort_values("total", ascending=False).head(8).to_string())
print("\nmismatching orders by order_status:")
print(mm["order_status"].value_counts().to_string())
print("\nmismatch rate by number of items in order:")
cmp_["items_n"] = cmp_["n_items"].clip(upper=3).map({1: "1", 2: "2", 3: "3+"})
print(cmp_.groupby("items_n")["mism"].agg(orders="size", mismatches="sum", rate="mean").to_string())
print("\n'paid LESS' with no voucher: ", int(((less["has_voucher"] == False)).sum()),
      "| 'paid MORE' with installments=1 and no voucher: ",
      int(((more["inst_gt1"] == False) & (more["has_voucher"] == False)).sum()))
print("\nreconciliation base: orders where paid == price only (no freight) within 0.01:",
      int(((cmp_["paid"] - cmp_["price"]).abs() <= 0.01).sum()), "/", len(cmp_),
      "| where paid == price+freight:", int((~cmp_["mism"]).sum()))

# ---------------------------------------------------------------- C
h("C1. GMV status exclusion (canceled, unavailable)")
oi_o = oi.merge(o[["order_id", "order_status", "order_purchase_timestamp"]], on="order_id")
excl = oi_o["order_status"].isin(["canceled", "unavailable"])
print(f"order_items rows: {len(oi_o)}; in canceled/unavailable orders: {int(excl.sum())}; "
      f"price excluded: {oi_o.loc[excl, 'price'].sum():,.2f} of {oi_o['price'].sum():,.2f} "
      f"({oi_o.loc[excl, 'price'].sum() / oi_o['price'].sum() * 100:.2f}%)")
print("order_items rows by status of their order:")
print(oi_o.groupby("order_status").agg(rows=("price", "size"), price=("price", "sum")).round(2).to_string())
print("orders with items in non-delivered, non-excluded status (still counted in GMV):",
      oi_o.loc[~excl & (oi_o["order_status"] != "delivered"), "order_id"].nunique())

h("C2. ADS date range 2017-01-01 .. 2018-08-31 (by purchase date)")
d = oi_o["order_purchase_timestamp"].dt.normalize()
inr = d.between("2017-01-01", "2018-08-31")
print(f"order_items rows in range: {int(inr.sum())}; outside: {int((~inr).sum())} "
      f"(before: {int((d < '2017-01-01').sum())}, after: {int((d > '2018-08-31').sum())})")
inr_gmv = inr & ~excl
print(f"GMV in range after status exclusion: {oi_o.loc[inr_gmv, 'price'].sum():,.2f}; rows: {int(inr_gmv.sum())}")
od = o["order_purchase_timestamp"].dt.normalize()
print(f"orders in range: {int(od.between('2017-01-01', '2018-08-31').sum())} of {len(o)}")

h("C3. Is the data complete at the tail? (daily order counts)")
daily = o.groupby(od).size()
print(daily["2018-08-10":"2018-09-10"].to_string())
print("last purchase:", o["order_purchase_timestamp"].max(), "| last approved:", o["order_approved_at"].max(),
      "| last delivered:", o["order_delivered_customer_date"].max())
last_dense = daily[daily >= 50].index.max()
print("last date with >=50 orders:", last_dense.date())
print("persons whose FIRST purchase is before 2017-01-01:",
      int((o.merge(c[["customer_id", "customer_unique_id"]], on="customer_id")
           .groupby("customer_unique_id")["order_purchase_timestamp"].min() < "2017-01-01").sum()))

h("C4. Timestamp anomaly flags (R: flag, exclude from delivery-time metrics)")
deliv = o["order_status"] == "delivered"
f_carrier_lt_appr = (o["order_delivered_carrier_date"] < o["order_approved_at"])
f_deliv_lt_carrier = (o["order_delivered_customer_date"] < o["order_delivered_carrier_date"])
f_deliv_missing = deliv & o["order_delivered_customer_date"].isna()
f_nondeliv_has = ~deliv & o["order_delivered_customer_date"].notna()
flags = pd.DataFrame({"carrier<approved": f_carrier_lt_appr, "delivered<carrier": f_deliv_lt_carrier,
                      "delivered_status_no_date": f_deliv_missing, "nondelivered_has_date": f_nondeliv_has})
for col in flags:
    print(f"{col}: {int(flags[col].sum())}")
print(f"any flag: {int(flags.any(axis=1).sum())}")
print(f"any flag except carrier<approved: {int(flags.drop(columns='carrier<approved').any(axis=1).sum())}")
elig = deliv & o["order_delivered_customer_date"].notna()
print(f"delivered with customer date: {int(elig.sum())}; "
      f"eligible for delivery-time metric (no flag): {int((elig & ~flags.any(axis=1)).sum())}; "
      f"if carrier<approved NOT excluded: {int((elig & ~flags.drop(columns='carrier<approved').any(axis=1)).sum())}")
print("\ncarrier<approved: how much earlier is carrier handover than approval?")
gap = (o.loc[f_carrier_lt_appr, "order_approved_at"] - o.loc[f_carrier_lt_appr, "order_delivered_carrier_date"]).dt.total_seconds()
print(cut_secs(gap, [0, 3600, 86400, 7 * 86400, np.inf], ["<=1h", "1h-1d", "1d-7d", ">7d"]).to_string())
print(f"median gap (h): {gap.median() / 3600:.1f}")
print("do those orders have a sane delivered-after-carrier date?",
      int((f_carrier_lt_appr & o["order_delivered_customer_date"].notna() & ~f_deliv_lt_carrier).sum()), "of",
      int((f_carrier_lt_appr & o["order_delivered_customer_date"].notna()).sum()))
print("\ndelivered<carrier gap (days):")
gap2 = (o.loc[f_deliv_lt_carrier, "order_delivered_carrier_date"] - o.loc[f_deliv_lt_carrier, "order_delivered_customer_date"]).dt.total_seconds() / 86400
print(gap2.describe().round(2).to_string())

h("C5. Reviews: latest review per order (tie check)")
cnt = r.groupby("order_id").size()
multi_orders = cnt[cnt > 1].index
rm = r[r["order_id"].isin(multi_orders)]
mx = rm.groupby("order_id")["review_answer_timestamp"].transform("max")
ties = rm[rm["review_answer_timestamp"] == mx].groupby("order_id").size()
print(f"orders with >1 review: {len(multi_orders)}; extra rows to drop when keeping 1 per order: {int(len(r) - r['order_id'].nunique())}")
print(f"orders where the latest answer_timestamp is tied: {int((ties > 1).sum())}")
mx_c = rm.groupby("order_id")["review_creation_date"].transform("max")
ties_c = rm[(rm["review_answer_timestamp"] == mx) & (rm["review_creation_date"] == mx_c)].groupby("order_id").size()
print(f"orders still tied after also using review_creation_date: {int((ties_c > 1).sum())}")
sc = rm.groupby("order_id")["review_score"].nunique()
print(f"orders with >1 review whose scores differ: {int((sc > 1).sum())}")

h("C6. Geolocation aggregation checks")
gz = "geolocation_zip_code_prefix"
inbox = g["geolocation_lat"].between(-34, 6) & g["geolocation_lng"].between(-74, -34)
g2 = g[inbox]
print(f"rows dropped by bounding box: {int((~inbox).sum())}; zip prefixes before: {g[gz].nunique()}, after: {g2[gz].nunique()}")
z2 = set(g2[gz])
print(f"customer rows with zip not in geolocation: before {int((~c['customer_zip_code_prefix'].isin(set(g[gz]))).sum())}, "
      f"after bbox drop {int((~c['customer_zip_code_prefix'].isin(z2)).sum())}")
print(f"seller rows with zip not in geolocation: before {int((~s['seller_zip_code_prefix'].isin(set(g[gz]))).sum())}, "
      f"after bbox drop {int((~s['seller_zip_code_prefix'].isin(z2)).sum())}")
cc = g2.groupby([gz, "geolocation_city"]).size().rename("n").reset_index()
top = cc.groupby(gz)["n"].agg(["max", lambda x: (x == x.max()).sum()])
top.columns = ["max", "n_top"]
print(f"zip prefixes where the most frequent city is tied: {int((top['n_top'] > 1).sum())} of {len(top)}")
cs = g2.groupby([gz, "geolocation_state"]).size().rename("n").reset_index()
tops = cs.groupby(gz)["n"].agg(lambda x: (x == x.max()).sum())
print(f"zip prefixes where the most frequent state is tied: {int((tops > 1).sum())}; "
      f"zip prefixes with >1 state: {int((cs.groupby(gz).size() > 1).sum())}")
mode_state = cs.sort_values(["n"], ascending=False).drop_duplicates(gz).set_index(gz)["geolocation_state"]
cm = c.assign(geo_state=c["customer_zip_code_prefix"].map(mode_state)).dropna(subset=["geo_state"])
print(f"customers whose state != geolocation mode state: {int((cm['customer_state'] != cm['geo_state']).sum())} of {len(cm)}")

h("C7. Zip prefixes shorter than 5 digits (need zero-padding)")
for name, ser in [("customers", c["customer_zip_code_prefix"]), ("sellers", s["seller_zip_code_prefix"]),
                  ("geolocation", g[gz])]:
    print(f"{name}: {int((ser < 10000).sum())} of {len(ser)} rows")

# ---------------------------------------------------------------- D (after decisions D1-D4, R14, P03)
import unicodedata


def norm_city(x):
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(x).lower()) if not unicodedata.combining(ch)).strip()


h("D1. data_end = 2018-08-23: incomplete cohorts and partial days")
oc = o.merge(c[["customer_id", "customer_unique_id"]], on="customer_id")
first = oc.groupby("customer_unique_id")["order_purchase_timestamp"].min().dt.normalize()
inw = first.between("2017-01-01", "2018-08-31")
data_end = pd.Timestamp("2018-08-23")
print(f"persons with first purchase in 2017-01-01..2018-08-31: {int(inw.sum())}")
for n_days in (7, 30):
    inc = inw & (first > data_end - pd.Timedelta(days=n_days))
    print(f"{n_days}d: incomplete cohort persons {int(inc.sum())} (first purchase after "
          f"{(data_end - pd.Timedelta(days=n_days)).date()}), complete {int((inw & ~inc).sum())}")
part = d.between("2018-08-24", "2018-08-31")
print(f"partial days 2018-08-24..31: orders {oi_o.loc[part, 'order_id'].nunique()}, item rows {int(part.sum())}, "
      f"GMV rows (after status exclusion) {int((part & ~excl).sum())}, GMV {oi_o.loc[part & ~excl, 'price'].sum():,.2f}")
print(f"orders purchased 2018-08-24..31 (all statuses): {int(od.between('2018-08-24', '2018-08-31').sum())}")

h("D2. Delivery-time population (exclude only delivered<carrier, delivered w/o date, non-delivered with date)")
bad = flags[["delivered<carrier", "delivered_status_no_date", "nondelivered_has_date"]].any(axis=1)
print(f"delivered with customer date: {int(elig.sum())}; eligible: {int((elig & ~bad).sum())}; excluded: {int((elig & bad).sum())}")

h("D4. Geolocation: drop exact duplicates, then bounding box, then aggregate")
gd = g.drop_duplicates()
print(f"rows raw {len(g)}; after exact-duplicate drop {len(gd)} (removed {len(g) - len(gd)})")
inbox_d = gd["geolocation_lat"].between(-34, 6) & gd["geolocation_lng"].between(-74, -34)
gd = gd[inbox_d]
print(f"bounding-box rows dropped after dedupe: {int((~inbox_d).sum())}; rows for aggregation: {len(gd)}; "
      f"zip prefixes: {gd[gz].nunique()}")
gd = gd.assign(city_n=gd["geolocation_city"].map(norm_city))
cc = gd.groupby([gz, "city_n"]).size().rename("n").reset_index()
print(f"prefixes with most frequent normalized city tied: {int((cc.groupby(gz)['n'].agg(lambda x: (x == x.max()).sum()) > 1).sum())}"
      f"; with >1 normalized city: {int((cc.groupby(gz).size() > 1).sum())}")
cs = gd.groupby([gz, "geolocation_state"]).size().rename("n").reset_index()
print(f"prefixes with most frequent state tied: {int((cs.groupby(gz)['n'].agg(lambda x: (x == x.max()).sum()) > 1).sum())}"
      f"; with >1 state: {int((cs.groupby(gz).size() > 1).sum())}")
mode_state = cs.sort_values(["n", "geolocation_state"], ascending=[False, True]).drop_duplicates(gz).set_index(gz)["geolocation_state"]
cm = c.assign(geo_state=c["customer_zip_code_prefix"].map(mode_state)).dropna(subset=["geo_state"])
print(f"customers state != modal state: {int((cm['customer_state'] != cm['geo_state']).sum())} of {len(cm)}")
zs = set(gd[gz])
print(f"customer rows without coordinates: {int((~c['customer_zip_code_prefix'].isin(zs)).sum())}; "
      f"seller rows without coordinates: {int((~s['seller_zip_code_prefix'].isin(zs)).sum())}")
med = gd.groupby(gz)[["geolocation_lat", "geolocation_lng"]].median()
print(f"median lat/lng rows: {len(med)}")

h("D5. R14: first_review_score vs latest review per order")
print(f"orders with a review: {r['order_id'].nunique()}; orders without a review: {len(o) - r['order_id'].nunique()}")
rm = r[r["order_id"].isin(multi_orders)]
first_r = (rm.sort_values(["order_id", "review_creation_date", "review_answer_timestamp", "review_id"])
           .groupby("order_id").head(1).set_index("order_id"))
last_r = (rm.sort_values(["order_id", "review_answer_timestamp", "review_creation_date", "review_id"],
                         ascending=[True, False, False, False]).groupby("order_id").head(1).set_index("order_id"))
print(f"orders with >1 review: {len(first_r)}; first score != latest score: "
      f"{int((first_r['review_score'] != last_r.loc[first_r.index, 'review_score']).sum())}; "
      f"first review row is also the latest row: {int((first_r['review_id'] == last_r.loc[first_r.index, 'review_id']).sum())}")
mn = rm.groupby("order_id")["review_creation_date"].transform("min")
t1 = rm[rm["review_creation_date"] == mn].groupby("order_id").size()
print(f"orders tied on earliest review_creation_date: {int((t1 > 1).sum())}")
mn2 = rm[rm["review_creation_date"] == mn].groupby("order_id")["review_answer_timestamp"].transform("min")
t2 = rm[rm["review_creation_date"] == mn].loc[lambda x: x["review_answer_timestamp"] == mn2].groupby("order_id").size()
print(f"orders still tied after answer_timestamp: {int((t2 > 1).sum())}")
sc = rm.groupby("order_id")["review_score"].agg(["first", "last"])

h("D6. P03 (R21): SCD Type 1 on dim_customer, attributes of the latest order")
cc2 = oc.merge(c[["customer_id", "customer_zip_code_prefix", "customer_city", "customer_state"]], on="customer_id")
attrs = ["customer_zip_code_prefix", "customer_city", "customer_state"]
nu = cc2.groupby("customer_unique_id")[attrs].nunique()
print(f"persons with >1 distinct zip/state: {int((nu[['customer_zip_code_prefix', 'customer_state']] > 1).any(axis=1).sum())}; "
      f"with any change in zip/city/state: {int((nu > 1).any(axis=1).sum())}")
mx = cc2.groupby("customer_unique_id")["order_purchase_timestamp"].transform("max")
latest = cc2[cc2["order_purchase_timestamp"] == mx]
tie = latest.groupby("customer_unique_id")[attrs].nunique()
print(f"persons whose latest purchase timestamp is shared by orders with different attributes: {int((tie > 1).any(axis=1).sum())}")
lat_one = latest.sort_values(["customer_unique_id", "order_id"]).drop_duplicates("customer_unique_id").set_index("customer_unique_id")
chg = cc2.join(lat_one[attrs], on="customer_unique_id", rsuffix="_latest")
diff_rows = (chg[attrs[0]] != chg[attrs[0] + "_latest"]) | (chg[attrs[1]] != chg[attrs[1] + "_latest"]) | (chg[attrs[2]] != chg[attrs[2] + "_latest"])
print(f"customer_id rows whose attributes differ from the person's latest order: {int(diff_rows.sum())}; dim_customer rows: {len(lat_one)}")

# ---------------------------------------------------------------- E (D6: only valid orders count for cohorts / repurchase)
h("E. D6: valid orders only (status not in canceled, unavailable)")
EXCL_STATUS = ["canceled", "unavailable"]
oc = o.merge(c[["customer_id", "customer_unique_id"]], on="customer_id")
valid = oc[~oc["order_status"].isin(EXCL_STATUS)]
n_persons = oc["customer_unique_id"].nunique()
first_all = oc.groupby("customer_unique_id")["order_purchase_timestamp"].min().dt.normalize()
first_valid = valid.groupby("customer_unique_id")["order_purchase_timestamp"].min().dt.normalize()
print(f"persons: {n_persons}; with >=1 valid order: {len(first_valid)}; excluded entirely: {n_persons - len(first_valid)}")
only = oc.groupby("customer_unique_id")["order_status"].agg(lambda x: x.isin(EXCL_STATUS).all())
ex_p = only[only].index
ex_orders = oc[oc["customer_unique_id"].isin(ex_p)]
print("excluded persons by status of their orders:", ex_orders.groupby("customer_unique_id")["order_status"]
      .agg(lambda x: "+".join(sorted(set(x)))).value_counts().to_dict(), "| their orders:", len(ex_orders))
first_row = oc.sort_values(["customer_unique_id", "order_purchase_timestamp", "order_id"]).drop_duplicates("customer_unique_id")
p_first_excl = first_row.loc[first_row["order_status"].isin(EXCL_STATUS), "customer_unique_id"]
p_first_excl_valid = p_first_excl[p_first_excl.isin(first_valid.index)]
print(f"persons whose earliest order is canceled/unavailable: {len(p_first_excl)}; "
      f"of them with a later valid order: {len(p_first_excl_valid)}; with none (excluded): {len(p_first_excl) - len(p_first_excl_valid)}")
fa = first_all.reindex(first_valid.index)
shift = (first_valid - fa).dt.days
chg = shift > 0
print(f"persons whose cohort DATE changes: {int(chg.sum())} (shift days: median {shift[chg].median():.0f}, "
      f"p90 {shift[chg].quantile(.9):.0f}, max {shift[chg].max()})")
win = lambda s: s.between("2017-01-01", "2018-08-31")
print(f"cohort in ADS window 2017-01-01..2018-08-31: all-orders definition {int(win(first_all).sum())}, "
      f"valid-orders definition {int(win(first_valid).sum())}")
print(f"cohort date moves across the window edge: into window {int((~win(fa) & win(first_valid) & chg).sum())}, "
      f"out of window {int((win(fa) & ~win(first_valid) & chg).sum())}")
print(f"persons whose first valid order is before 2017-01-01: {int((first_valid < '2017-01-01').sum())}")
n_valid = valid.groupby("customer_unique_id")["order_id"].nunique()
rep = int((n_valid > 1).sum())
print(f"repurchase (>1 valid order): {rep} of {len(n_valid)} persons with a valid order = {rep / len(n_valid) * 100:.2f}% "
      f"(was 2,997 of 96,096 = 3.12% with all orders); max valid orders {n_valid.max()}")
nd = valid.assign(dt=valid["order_purchase_timestamp"].dt.normalize()).groupby("customer_unique_id")["dt"].nunique()
rep_d = int((nd > 1).sum())
print(f"repurchase on a later calendar day (>=2 distinct purchase dates): {rep_d} = {rep_d / len(nd) * 100:.2f}%")
old_rep = oc.groupby("customer_unique_id")["order_id"].nunique()
lost = old_rep[(old_rep > 1)].index.difference(n_valid[n_valid > 1].index)
print(f"persons repeat under all-orders but not under valid-orders: {len(lost)}")
data_end = pd.Timestamp("2018-08-23")
inw = win(first_valid)
for n_days in (7, 30):
    inc = inw & (first_valid > data_end - pd.Timedelta(days=n_days))
    print(f"{n_days}d: incomplete cohort persons {int(inc.sum())}, complete {int((inw & ~inc).sum())}")

# ---------------------------------------------------------------- F (D6 + D7: repurchase = valid orders on >= 2 distinct purchase dates)
h("F. D6 + D7 combined: repurchase and midnight edge case")
v = valid.assign(dt=valid["order_purchase_timestamp"].dt.normalize())
per = v.groupby("customer_unique_id").agg(n_orders=("order_id", "nunique"), n_dates=("dt", "nunique"),
                                          first_ts=("order_purchase_timestamp", "min"),
                                          last_ts=("order_purchase_timestamp", "max"),
                                          cohort=("dt", "min"))
base = len(per)
rep2 = per["n_dates"] > 1
print(f"persons with a valid order: {base}; repurchasers (>=2 distinct valid purchase dates): {int(rep2.sum())} = {rep2.mean() * 100:.2f}%")
print(f"  step by step: all-orders >1 order 2,997 (3.12% of 96,096) -> valid orders >1 order {int((per['n_orders'] > 1).sum())} "
      f"-> >=2 distinct dates {int(rep2.sum())}")
print("persons by number of distinct purchase dates:", per["n_dates"].clip(upper=4).value_counts().sort_index().to_dict(), "(4 = 4+)")
print(f"max distinct dates: {per['n_dates'].max()}; extra purchase occasions beyond the first: {int((per['n_dates'] - 1).sum())}")
same_day_only = (per["n_orders"] > 1) & ~rep2
print(f"persons with several valid orders but all on one date (one purchase occasion): {int(same_day_only.sum())}")
inwin = per["cohort"].between("2017-01-01", "2018-08-31")
print(f"cohorts in ADS window: {int(inwin.sum())}; repurchasers among them: {int((rep2 & inwin).sum())} = {(rep2 & inwin).sum() / inwin.sum() * 100:.2f}%")
print(f"repurchasers whose cohort is before the window: {int((rep2 & (per['cohort'] < '2017-01-01')).sum())}, after: {int((rep2 & (per['cohort'] > '2018-08-31')).sum())}")
span_h = (per["last_ts"] - per["first_ts"]).dt.total_seconds() / 3600
r2 = per[rep2].assign(span_h=span_h[rep2])
print("midnight edge case: repurchasers whose whole first->last span is short (the 2nd 'date' is only past midnight):")
for hrs in (1, 6, 24):
    print(f"  span < {hrs}h: {int((r2['span_h'] < hrs).sum())} persons ({(r2['span_h'] < hrs).mean() * 100:.1f}% of repurchasers)")
fv = v.sort_values(["customer_unique_id", "order_purchase_timestamp"])
fv["d0"] = fv.groupby("customer_unique_id")["dt"].transform("min")
later = fv[fv["dt"] > fv["d0"]].groupby("customer_unique_id")["order_purchase_timestamp"].min()
lastd0 = fv[fv["dt"] == fv["d0"]].groupby("customer_unique_id")["order_purchase_timestamp"].max()
g1 = (later - lastd0.reindex(later.index)).dt.total_seconds() / 3600
print(f"gap between last order on cohort day and first order on a later date (hours): "
      f"<1h {int((g1 < 1).sum())}, <6h {int((g1 < 6).sum())}, <24h {int((g1 < 24).sum())} of {len(g1)}")
day_off = (later.dt.normalize() - per.loc[later.index, "cohort"]).dt.days
print("first return at day offset 1 / 2-7 / 8-30 / >30:", int((day_off == 1).sum()), int(day_off.between(2, 7).sum()),
      int(day_off.between(8, 30).sum()), int((day_off > 30).sum()), "| returns on day 0 are not counted by construction")
