"""Round 2: one shop's orders, customers and products, with real junk in its ID columns.

Online Retail II: every line a UK gift retailer invoiced from December 2009 to December 2011, one
file, with no package for its system. The junk is the shop's own:

- customer IDs written as decimals (`13085.0`), and 243,007 lines with no customer;
- cancellations as invoices of their own (`C489449`), and six adjustments (`A506401`);
- 173 product codes also spelled in lower case (`85123a`), 160 of them with the same description;
- 17 codes that aren't products: postage, carriage, fees, discounts, manual entries, samples, tests;
- 9 gift vouchers (`gift_0001_10`): sold on invoices, but stock no one holds. Whether they are
  products is a judgement, so they are reported apart;
- one code with a trailing space (`47503J `), and an invoice listing one product on several lines.

The answer key is computed from the file the agent was given, so it holds for a sample too.
"""

import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

from score import has_attr, rows, survivors

FILE = "shop/online_retail_II.csv"
NOT_PRODUCTS = {"ADJUST", "ADJUST2", "AMAZONFEE", "B", "BANK CHARGES", "C2", "C3", "CRUK", "D", "DOT", "GIFT", "M",
                "m", "POST", "S", "TEST001", "TEST002"}  # GIFT: one line, no description, quantity -9


def voucher(code: str) -> bool:
    return code.upper().startswith("GIFT_")


def read(folder: Path) -> list[dict]:
    path = folder / FILE
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]


def customer(v: str) -> str:
    """A customer ID as the shop means it: `13085.0` is customer 13085."""
    return v[:-2] if v.endswith(".0") else v


def product(code: str) -> str:
    return code.strip().upper()


def spelled_two_ways(lines: list[dict]) -> dict[str, set[str]]:
    """Products the file spells in two cases, where both spellings carry the same description."""
    desc = defaultdict(Counter)
    for r in lines:
        desc[r["StockCode"]][r["Description"]] += 1
    out = defaultdict(set)
    for code in desc:
        if code not in NOT_PRODUCTS and not voucher(code):
            out[product(code)].add(code)
    top = lambda c: desc[c].most_common(1)[0][0]
    return {p: cs for p, cs in out.items() if len(cs) > 1 and len({top(c) for c in cs}) == 1}


def sample(dataset: Path, exports: Path, n: int) -> None:
    """Every line of: the invoices of n customers; n invoices with no customer; up to 20 invoices
    for each code that isn't a product, each voucher and each lower-case spelling of a product; and
    the invoices the questions name."""
    lines = read(dataset)
    lower = {c for cs in spelled_two_ways(lines).values() for c in cs if c != c.upper()}
    customers = set(sorted({r["Customer ID"] for r in lines if r["Customer ID"]})[:n])
    keep = set(sorted({r["Invoice"] for r in lines if not r["Customer ID"]})[:n]) | {"489434"}
    per_code = defaultdict(set)
    for r in lines:
        if r["Customer ID"] in customers or customer(r["Customer ID"]) == "12346":
            keep.add(r["Invoice"])
        code = r["StockCode"]
        if (code in NOT_PRODUCTS or voucher(code) or code in lower or code == "47503J") and len(per_code[code]) < 20:
            per_code[code].add(r["Invoice"])
    keep |= set().union(*per_code.values())
    (exports / FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(dataset / FILE, newline="", encoding="utf-8-sig") as f, open(exports / FILE, "w", newline="") as out:
        reader = csv.DictReader(f)
        writer = csv.DictWriter(out, reader.fieldnames)
        writer.writeheader()
        writer.writerows(r for r in reader if r["Invoice"] in keep)


QUESTIONS = (
    {"id": 1, "text": "Which customer placed invoice 489434?", "columns": ["customer ID"]},
    {"id": 2, "text": "How many invoices did customer 12346 have, cancellations included?", "columns": ["invoices"]},
    {"id": 3, "text": "How many different products were on invoice 489434?", "columns": ["products"]},
    {"id": 4, "text": "How many invoices included product 85123A?", "columns": ["invoices"]},
    {"id": 5, "text": "How many cancellations are there?", "columns": ["cancellations"]},
    {"id": 6, "text": "How many customers have an invoice, not counting cancellations, that includes product 22423?",
     "columns": ["customers"]},
)


def answers(folder: Path) -> dict[int, list]:
    lines = read(folder)
    invoices = {r["Invoice"] for r in lines}
    return {
        1: [[customer(c)] for c in sorted({r["Customer ID"] for r in lines if r["Invoice"] == "489434"} - {""})],
        2: [[len({r["Invoice"] for r in lines if customer(r["Customer ID"]) == "12346"})]],
        3: [[len({product(r["StockCode"]) for r in lines if r["Invoice"] == "489434"})]],
        4: [[len({r["Invoice"] for r in lines if product(r["StockCode"]) == "85123A"})]],
        5: [[sum(1 for i in invoices if i.startswith("C"))]],
        6: [[len({r["Customer ID"] for r in lines if product(r["StockCode"]) == "22423" and r["Customer ID"]
                  and not r["Invoice"].startswith("C")})]],
    }


def holder(conn, values: set[str]) -> tuple[str | None, set]:
    """The identity attribute holding most of `values`, and its entities' values."""
    best, held = None, set()
    for (ident,) in rows(conn, """select ident from attr where uniq = 'identity' and type = 'string'
                                  and ident not like 'fs/%%' and ident <> 'document/hash'"""):
        vs = {v for (v,) in rows(conn, f'select v from current."{ident}"')}
        if len(vs & values) > len(held & values):
            best, held = ident, vs
    return best, held


def truth(conn, folder: Path) -> dict:
    """The store's index of the shop against the file. Counts only. The shop has no package, so
    each kind of record is found by its IDs: the identity attribute holding most of them."""
    lines = read(folder)
    root = survivors(conn)
    one = lambda e: root.get(e, e)
    out = {}

    customers = {customer(r["Customer ID"]) for r in lines if r["Customer ID"]}
    raw_customers = {r["Customer ID"] for r in lines if r["Customer ID"]}
    ident, held = holder(conn, customers | raw_customers)
    out["customers"] = {"in_file": len(customers), "attribute": ident,
                        "in_store": len(held & customers), "as_decimals": len(held & (raw_customers - customers))}

    # Invoices, apart from the six bad-debt adjustments (`A506401`): ledger entries, which the
    # catalogue never indexes. Reported on their own.
    invoices = {r["Invoice"] for r in lines if not r["Invoice"].startswith("A")}
    adjustments = {r["Invoice"] for r in lines if r["Invoice"].startswith("A")}
    inv_ident, inv_held = holder(conn, invoices)
    out["invoices"] = {"in_file": len(invoices), "attribute": inv_ident, "in_store": len(inv_held & invoices),
                       "adjustments_in_file": len(adjustments), "adjustments_in_store": len(inv_held & adjustments),
                       "cancellations_in_file": sum(1 for i in invoices if i.startswith("C")),
                       "cancellations_in_store": sum(1 for i in inv_held & invoices if i.startswith("C"))}
    # Invoices that name a customer: does the store point each at its customer?
    if inv_ident and ident:
        named = {r["Invoice"]: customer(r["Customer ID"]) for r in lines if r["Customer ID"] and r["Invoice"] in invoices}
        inv_e = dict(rows(conn, f'select v, e from current."{inv_ident}"'))
        cust_v = dict(rows(conn, f'select e, v from current."{ident}"'))
        refs = defaultdict(set)
        for e, v in rows(conn, "select e, v_ref from cur where v_ref is not null"):
            if v in cust_v:
                refs[e].add(customer(cust_v[v]))
        out["invoices"]["naming_a_customer"] = len(named)
        out["invoices"]["pointing_at_it"] = sum(1 for i, c in named.items() if c in refs.get(inv_e.get(i), ()))

    codes = {r["StockCode"] for r in lines}
    products = {product(c) for c in codes if c not in NOT_PRODUCTS and not voucher(c)}
    vouchers = {product(c) for c in codes if voucher(c)}
    p_ident, p_held = holder(conn, products | codes)
    hubs = defaultdict(set)
    if p_ident:
        for e, v in rows(conn, f'select e, v from current."{p_ident}"'):
            hubs[product(v)].add(one(e))
    spelled = spelled_two_ways(lines)
    out["products"] = {
        "in_file": len(products), "attribute": p_ident, "in_store": sum(1 for p in products if p in hubs),
        "spelled_two_ways": len(spelled), "split_in_store": sum(1 for p in spelled if len(hubs.get(p, ())) > 1),
        "lower_case_twins": sum(1 for v in p_held if v != v.upper() and v.upper() in p_held),
        "codes_with_spaces": sum(1 for v in p_held if v != v.strip()),
        "not_products_in_file": len({c for c in codes if c in NOT_PRODUCTS}),
        "not_products_as_products": sum(1 for v in p_held if v in NOT_PRODUCTS or v.upper() in NOT_PRODUCTS),
        "gift_vouchers_in_file": len(vouchers), "gift_vouchers_as_products": sum(1 for p in vouchers if p in hubs),
    }
    # Lines: entities that are core/part_of an invoice. An invoice lists one product on several
    # lines 45,950 times, 31,478 of them identical rows; a line keyed by IDs is one per pair.
    if inv_ident and has_attr(conn, "core/part_of"):
        pairs = {(r["Invoice"], product(r["StockCode"])) for r in lines if r["Invoice"] in invoices}
        out["lines"] = {"invoice_and_product_pairs": len(pairs),
                        "in_store": rows(conn, f"""select count(*) from current."core/part_of" p
                                                   join current."{inv_ident}" i on i.e = p.v""")[0][0]}
    return out
