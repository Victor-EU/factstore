"""Round 3: a marketplace at scale, with a second dataset joined in and duplicate customers.

Olist, a Brazilian marketplace: 99,441 orders from 2016 to 2018, their items, payments and reviews,
the customers, products and sellers; and its sales team's funnel, 8,000 marketing leads and the
842 sellers it closed. No package covers the marketplace, so the catalogue names its identifiers.
What makes it hard:

- a customer ID per order. `customer_unique_id` says which are one person: 2,997 people hold
  6,342 of them, one up to 17. The answer key for duplicates;
- an order's items are numbered by the source (`order_item_id`), and one product repeats on an
  order 10,225 times: an order of 21 items holds 3 products. Each item is a unit sold, so one
  record per product loses units;
- 789 review IDs sit on more than one order, so a review ID alone isn't unique;
- 462 of the 842 closed sellers sold nothing in the marketplace's export: the funnel names
  sellers the marketplace never lists;
- the geolocation file's million rows have no ID, and name no record;
- review comments are written by customers: personal data that must stay in the source.

The answer key is computed from the files the agent was given, so it holds for a sample too.
"""

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

from score import rows, survivors

M, F = "marketplace", "funnel"
CUSTOMERS, ORDERS = f"{M}/olist_customers_dataset.csv", f"{M}/olist_orders_dataset.csv"
ITEMS, PAYMENTS = f"{M}/olist_order_items_dataset.csv", f"{M}/olist_order_payments_dataset.csv"
REVIEWS, PRODUCTS = f"{M}/olist_order_reviews_dataset.csv", f"{M}/olist_products_dataset.csv"
SELLERS, GEO = f"{M}/olist_sellers_dataset.csv", f"{M}/olist_geolocation_dataset.csv"
TRANSLATION = f"{M}/product_category_name_translation.csv"
LEADS, DEALS = f"{F}/olist_marketing_qualified_leads_dataset.csv", f"{F}/olist_closed_deals_dataset.csv"

# The questions' cases, chosen by script from the full files.
ORDER_OF_FIVE_SELLERS = "1c11d0f4353b31ac3417fbfa5f0f2a8a"
PERSON_OF_17 = "8d50f5eadf50201ccdcedfb9e2ac8455"  # customer_unique_id
CUSTOMER_OF_17 = "0bf8bf19944a7f8b40ba86fef778ca7c"  # the first of its 17 customer IDs
ORDER_OF_21_ITEMS = "8272b63d03f5f79c56e9e4120aec44ef"  # 3 products
PRODUCT_ON_467 = "99a4788cb24856965c36a24e339b6058"
CLOSED_SELLER = "7d13fca15225358621be4086e1eb0964"
REVIEW_ON_3 = "f4bb9d6dd4fb6dcc2298f0e7b17b8e1e"


def read(folder: Path, name: str) -> list[dict]:
    path = folder / name
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(f)]


def person_ids(customers: list[dict]) -> dict[str, list[str]]:
    out = defaultdict(list)
    for r in customers:
        out[r["customer_unique_id"]].append(r["customer_id"])
    return out


def write(dataset: Path, exports: Path, name: str, keep) -> None:
    (exports / name).parent.mkdir(parents=True, exist_ok=True)
    with open(dataset / name, newline="", encoding="utf-8-sig") as f, open(exports / name, "w", newline="") as out:
        reader = csv.DictReader(f)
        writer = csv.DictWriter(out, reader.fieldnames)
        writer.writeheader()
        writer.writerows(r for r in reader if keep(r))


def sample(dataset: Path, exports: Path, n: int) -> None:
    """The orders of n people who hold several customer IDs, and n other orders; the orders the
    questions name, and every order of the product in question 4; with every row that names them,
    the customers, products and sellers they name, and each review's other orders. The funnel's
    deals with those sellers, n/4 deals with sellers who sold nothing, and their leads with n more.
    Up to 3 geolocation rows for each postcode the sample names."""
    customers, orders, items = read(dataset, CUSTOMERS), read(dataset, ORDERS), read(dataset, ITEMS)
    reviews, deals, leads = read(dataset, REVIEWS), read(dataset, DEALS), read(dataset, LEADS)
    people = person_ids(customers)
    several = sorted(u for u, ids in people.items() if len(ids) > 1)[:n]
    wanted = {c for u in several + [PERSON_OF_17] for c in people[u]}
    keep = {r["order_id"] for r in orders if r["customer_id"] in wanted}
    keep |= set(sorted(r["order_id"] for r in orders)[:n])
    keep |= {ORDER_OF_FIVE_SELLERS, ORDER_OF_21_ITEMS} | {r["order_id"] for r in items if r["product_id"] == PRODUCT_ON_467}
    keep |= {r["order_id"] for r in reviews if r["review_id"] == REVIEW_ON_3}
    by_review = defaultdict(set)
    for r in reviews:
        by_review[r["review_id"]].add(r["order_id"])
    keep |= {o for r in reviews if r["order_id"] in keep for o in by_review[r["review_id"]]}
    custs = {r["customer_id"] for r in orders if r["order_id"] in keep}
    kept_items = [r for r in items if r["order_id"] in keep]
    products = {r["product_id"] for r in kept_items}
    sellers = {r["seller_id"] for r in kept_items}
    sold = {r["seller_id"] for r in items}
    kept_deals = {r["mql_id"] for r in deals if r["seller_id"] in sellers or r["seller_id"] == CLOSED_SELLER}
    kept_deals |= set(sorted(r["mql_id"] for r in deals if r["seller_id"] not in sold)[:max(n // 4, 1)])
    sellers |= {r["seller_id"] for r in deals if r["mql_id"] in kept_deals}
    kept_leads = kept_deals | set(sorted(r["mql_id"] for r in leads if r["mql_id"] not in kept_deals)[:n])
    zips = {r["customer_zip_code_prefix"] for r in customers if r["customer_id"] in custs}
    zips |= {r["seller_zip_code_prefix"] for r in read(dataset, SELLERS) if r["seller_id"] in sellers}
    per_zip = Counter()

    def geo(r):
        z = r["geolocation_zip_code_prefix"]
        per_zip[z] += z in zips
        return z in zips and per_zip[z] <= 3

    write(dataset, exports, CUSTOMERS, lambda r: r["customer_id"] in custs)
    for name in (ORDERS, ITEMS, PAYMENTS, REVIEWS):
        write(dataset, exports, name, lambda r: r["order_id"] in keep)
    write(dataset, exports, PRODUCTS, lambda r: r["product_id"] in products)
    write(dataset, exports, SELLERS, lambda r: r["seller_id"] in sellers)
    write(dataset, exports, GEO, geo)
    write(dataset, exports, TRANSLATION, lambda r: True)
    write(dataset, exports, DEALS, lambda r: r["mql_id"] in kept_deals)
    write(dataset, exports, LEADS, lambda r: r["mql_id"] in kept_leads)


QUESTIONS = (
    {"id": 1, "text": f"Which sellers sold the items on order {ORDER_OF_FIVE_SELLERS}?", "columns": ["seller ID"]},
    {"id": 2, "text": f"How many orders has the person behind customer {CUSTOMER_OF_17} placed, counting every "
                      "customer ID that is the same person?", "columns": ["orders"]},
    {"id": 3, "text": f"How many items were on order {ORDER_OF_21_ITEMS}? Each item is one unit.", "columns": ["items"]},
    {"id": 4, "text": f"How many orders included product {PRODUCT_ON_467}?", "columns": ["orders"]},
    {"id": 5, "text": "How many of the sellers our sales team closed have sold anything on the marketplace?",
     "columns": ["sellers"]},
    {"id": 6, "text": f"Which marketing lead did seller {CLOSED_SELLER} come from?", "columns": ["lead ID"]},
    {"id": 7, "text": f"Which orders does review {REVIEW_ON_3} belong to?", "columns": ["order ID"]},
)


def answers(folder: Path) -> dict[int, list]:
    customers, orders, items = read(folder, CUSTOMERS), read(folder, ORDERS), read(folder, ITEMS)
    reviews, deals = read(folder, REVIEWS), read(folder, DEALS)
    ids = set(person_ids(customers)[PERSON_OF_17])
    sold = {r["seller_id"] for r in items}
    return {
        1: [[s] for s in sorted({r["seller_id"] for r in items if r["order_id"] == ORDER_OF_FIVE_SELLERS})],
        2: [[sum(1 for r in orders if r["customer_id"] in ids)]],
        3: [[sum(1 for r in items if r["order_id"] == ORDER_OF_21_ITEMS)]],
        4: [[len({r["order_id"] for r in items if r["product_id"] == PRODUCT_ON_467})]],
        5: [[len({r["seller_id"] for r in deals} & sold)]],
        6: [[r["mql_id"]] for r in deals if r["seller_id"] == CLOSED_SELLER],
        7: [[o] for o in sorted({r["order_id"] for r in reviews if r["review_id"] == REVIEW_ON_3})],
    }


# --- the answer key against the store --------------------------------------------------------------

HEX = re.compile(r"[0-9a-f]{32}")


def identity_values(conn) -> dict[str, dict[str, int]]:
    """Each identity attribute's values and their entities."""
    out = {}
    for (ident,) in rows(conn, """select ident from attr where uniq = 'identity' and type = 'string'
                                  and ident not like 'fs/%%' and ident <> 'document/hash'"""):
        out[ident] = dict(rows(conn, f'select v, e from current."{ident}"'))
    return out


def holder(held: dict[str, dict[str, int]], ids: set[str], tokens: bool = False) -> tuple[str | None, dict]:
    """The identity attribute holding most of `ids`, as {id: entity}. With `tokens`, an ID counts
    when it is part of a value, as in a key built from it (`<review>/<order>`)."""
    best, found = None, {}
    for ident, values in held.items():
        got = defaultdict(list)
        for v, e in values.items():
            for t in (HEX.findall(v) if tokens else [v]):
                if t in ids:
                    got[t].append(e)
        if len(got) > len(found):
            best, found = ident, got
    return best, found


def any_values(conn, ids: set[str]) -> tuple[str | None, dict[int, str]]:
    """The attribute, identity or not, holding most of `ids`, as {entity: value}."""
    best, found = None, {}
    for (ident,) in rows(conn, "select ident from attr where type = 'string' and ident not like 'fs/%%'"):
        got = {e: v for e, v in rows(conn, f'select e, v from current."{ident}"') if v in ids}
        if len(set(got.values())) > len(set(found.values())):
            best, found = ident, got
    return best, found


def truth(conn, folder: Path) -> dict:
    """The store's index of the marketplace and the funnel against the files. Counts only. With no
    package, each kind of record is found by its IDs: the identity attribute holding most of them."""
    customers, orders, items = read(folder, CUSTOMERS), read(folder, ORDERS), read(folder, ITEMS)
    payments, reviews = read(folder, PAYMENTS), read(folder, REVIEWS)
    products, sellers = read(folder, PRODUCTS), read(folder, SELLERS)
    deals, leads = read(folder, DEALS), read(folder, LEADS)
    root = survivors(conn)
    one = lambda e: root.get(e, e)
    held = identity_values(conn)
    refs = defaultdict(set)
    for e, t in rows(conn, "select e, v_ref from cur where v_ref is not null"):
        refs[e].add(t)
    back = defaultdict(set)
    for e, ts in refs.items():
        for t in ts:
            back[t].add(e)
    out = {}

    def kind(name, values, tokens=False):
        ident, found = holder(held, values, tokens)
        out[name] = {"in_file": len(values), "attribute": ident, "in_store": len(found)}
        return {k: v[0] for k, v in found.items()}

    cust_e = kind("customers", {r["customer_id"] for r in customers})
    order_e = kind("orders", {r["order_id"] for r in orders})
    product_e = kind("products", {r["product_id"] for r in products} | {r["product_id"] for r in items})
    seller_e = kind("sellers", {r["seller_id"] for r in sellers} | {r["seller_id"] for r in deals})
    lead_e = kind("leads", {r["mql_id"] for r in leads} | {r["mql_id"] for r in deals})
    out["sellers"]["only_in_the_funnel"] = len({r["seller_id"] for r in deals} - {r["seller_id"] for r in sellers})

    # People: the customer IDs that customer_unique_id makes one person. Joined when the store
    # gives all of a person's IDs one key: the person's ID, on them or on a record they point at,
    # or the account their core/same_as chains end at.
    people = {u: ids for u, ids in person_ids(customers).items()}
    u_attr, u_of = any_values(conn, set(people))

    def key(e):
        for x in (e, one(e)):
            if x in u_of:
                return u_of[x]
            for t in refs.get(x, ()):
                if one(t) in u_of or t in u_of:
                    return u_of.get(t) or u_of[one(t)]
        return one(e)

    several = {u: ids for u, ids in people.items() if len(ids) > 1}
    keys = {c: key(cust_e[c]) for c in cust_e}
    true_of = defaultdict(set)
    for u, ids in people.items():
        for c in ids:
            if c in keys:
                true_of[keys[c]].add(u)
    out["people"] = {"with_several_ids": len(several), "their_ids": sum(len(v) for v in several.values()),
                     "attribute": u_attr,
                     "joined": sum(1 for ids in several.values() if all(c in keys for c in ids)
                                   and len({keys[c] for c in ids}) == 1),
                     "keys_joining_two_people": sum(1 for us in true_of.values() if len(us) > 1)}

    # Orders point at their customer.
    out["orders"]["pointing_at_customer"] = sum(
        1 for r in orders if r["order_id"] in order_e and r["customer_id"] in cust_e
        and {one(t) for t in refs.get(order_e[r["order_id"]], ())} & {one(cust_e[r["customer_id"]])})

    # Items: records pointing at an order and at a product. Each item is a unit, numbered by the source.
    order_set, product_set, seller_set = set(order_e.values()), set(product_e.values()), set(seller_e.values())
    per_order = Counter(r["order_id"] for r in items)
    item_es = {e for o in order_set for e in back.get(o, ()) if refs[e] & product_set}
    stored = Counter(o for o in order_e if o in per_order for e in back.get(order_e[o], ()) if e in item_es)
    out["items"] = {"in_file": len(items), "order_and_product_pairs": len({(r["order_id"], r["product_id"]) for r in items}),
                    "in_store": len(item_es), "orders_with_every_item": sum(1 for o, k in per_order.items() if stored[o] == k),
                    "orders_with_items": len(per_order), "pointing_at_seller": sum(1 for e in item_es if refs[e] & seller_set)}

    # Reviews: a review ID alone isn't unique, so each (review, order) pair is checked.
    pairs = {(r["review_id"], r["order_id"]) for r in reviews}
    r_attr, r_found = holder(held, {r for r, _ in pairs}, tokens=True)
    by_rid = defaultdict(set)
    for rid, es in r_found.items():
        for e in es:
            by_rid[rid] |= {one(t) for t in refs.get(e, ())}
    out["reviews"] = {"in_file": len(pairs), "review_ids": len({r for r, _ in pairs}),
                      "review_ids_on_several_orders": sum(1 for v in Counter(r for r, _ in pairs).values() if v > 1),
                      "attribute": r_attr, "in_store": sum(len(es) for es in r_found.values()),
                      "pairs_right": sum(1 for rid, o in pairs if o in order_e and one(order_e[o]) in by_rid.get(rid, ()))}

    # What points at orders, by the identity of the record pointing: items, payments, reviews.
    pointing = Counter()
    ident_of = {e: ident for ident, values in held.items() for e in values.values()}
    for o in order_set:
        for e in back.get(o, ()):
            pointing[ident_of.get(e, "no identity")] += 1
    out["records_pointing_at_orders"] = dict(pointing.most_common())
    out["payments_in_file"] = len(payments)

    # The funnel: each closed seller linked to its lead, directly or through one record (the deal).
    def linked(a, b):
        near = lambda x: refs.get(x, set()) | back.get(x, set())
        na = near(a)
        return b in na or any(b in near(x) for x in na if len(near(x)) <= 10)

    out["deals"] = {"in_file": len(deals),
                    "seller_linked_to_lead": sum(1 for r in deals if r["seller_id"] in seller_e and r["mql_id"] in lead_e
                                                 and linked(seller_e[r["seller_id"]], lead_e[r["mql_id"]]))}

    # What names no record: postcodes and categories indexed as records are reported.
    zips = {r["geolocation_zip_code_prefix"] for r in read(folder, GEO)}
    cats = {r["product_category_name"] for r in products if r["product_category_name"]}
    out["indexed_but_not_records"] = {"postcodes": len(holder(held, zips)[1]), "categories": len(holder(held, cats)[1])}
    return out
