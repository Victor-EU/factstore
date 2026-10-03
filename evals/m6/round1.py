"""Round 1: one product list across the marketplaces a brand sells on.

An Indian clothing seller's reports: Amazon's order report (seller SKU, ASIN, order ID), an
international sales report, the stock report and two price lists. The first three share one code
scheme, the brand's SKU code (`JNE3781-KR-XXXL`), with real mess in it:

- codes with a trailing full stop, a double space or a lowercase letter (`JNE3435-KR-XXxL`);
- an Excel error (`#REF!`) and blanks in the stock report's SKU column;
- a size range typed as a code (`JAN8641-S TO XXL`), two codes run together (`J0210-DR-XL1J0210-DR-XL`),
  a header repeated as data (`SKU`), category words (`KURTI`), and charges sold as lines (`SHIPPING`);
- 10 ASINs Amazon lists under two of our codes each, and 5 codes listed under two ASINs. Most pairs
  look like one product listed twice (`J0184-KR-S`, `J0184-KR-A-S`), but one is two styles
  (`AN208-MUSTARD-M`, `CH208-MUSTARD-M`). Since ecom-ops 0.4.0 a listing is a record of its own, so
  the store holds both listings under the one ASIN without calling them one product: question 6.

The price lists use another scheme (`Os206_3141_S`) that shares no code with the rest. Nothing in
the data links them, so any link the store makes to them is wrong.

The answer key is computed from the files the agent was given, so it holds for a sample too. A
sample keeps whole products, not the first rows of each file, so that the files still share codes.
"""

import csv
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from score import has_attr, rows, survivors

AMAZON, INTERNATIONAL, STOCK = "reports/Amazon Sale Report.csv", "reports/International sale Report.csv", "reports/Sale Report.csv"
PRICE_LISTS = ("reports/May-2022.csv", "reports/P  L March 2021.csv")
NOT_PRODUCTS = {"LABEL CHARGE", "LABEL MANUF.CHRAGE", "SHIPPING", "SHIPPING CHARGES", "TAG PRINTING", "TAGS",
                "TAGS(LABOUR)"}


def norm(code: str) -> str:
    """A code as the brand means it: no whitespace, no trailing full stop, upper case."""
    return re.sub(r"\s+", "", code).rstrip(".").upper()


def junk(code: str) -> bool:
    """Not a code: a blank, an Excel error, a size range, a word with no digit (a header or a
    category), or two codes run together."""
    style = code.split("-")[0].upper()
    return (not code or code == "#REF!" or " TO " in code.upper() or not re.search(r"\d", code)
            or (len(style) > 3 and code.upper().count(style) > 1))


def read(folder: Path, name: str) -> list[dict]:
    path = folder / name
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(f)]


def sample(dataset: Path, exports: Path, n: int) -> None:
    """n product styles, and every row of the three files that names one: the styles the questions
    and the answer key's hard cases need, then the most sold. Plus the junk rows, the first n rows
    of each price list, and the other files whole."""
    lines, _, codes, orders = amazon(dataset)
    style = lambda code: code.split("-")[0].upper()
    asked = {"JNE3781-KR-XXXL", "JNE3797-KR-L", *codes["B09KXVBD7Z"], *codes["B08B4TP9NR"],
             *orders["171-2644368-7969167"]}
    hard = [c for cs in product_codes(dataset).values() if len(cs) > 1 for c in cs]
    hard += [c for cs in codes.values() if len(cs) > 1 for c in cs]
    keep = {style(c) for c in [*asked, *hard]}
    for c, _ in Counter(r["SKU"] for r in lines).most_common():
        if len(keep) >= n:
            break
        keep.add(style(c))
    for name, column in ((AMAZON, "SKU"), (INTERNATIONAL, "SKU"), (STOCK, "SKU Code")):
        write(dataset / name, exports / name, lambda r: style(r.get(column) or "") in keep
              or junk((r.get(column) or "").strip()) or (r.get(column) or "").strip() in NOT_PRODUCTS)
    for name in PRICE_LISTS:
        write(dataset / name, exports / name, lambda r, seen=Counter(): seen.update("n") or seen["n"] <= n)
    for path in (dataset / "reports").iterdir():
        if not (exports / "reports" / path.name).exists():
            shutil.copy2(path, exports / "reports" / path.name)


def write(source: Path, dest: Path, keep) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(source, newline="", encoding="utf-8-sig") as f, open(dest, "w", newline="") as out:
        reader = csv.DictReader(f)
        writer = csv.DictWriter(out, reader.fieldnames)
        writer.writeheader()
        writer.writerows(r for r in reader if keep(r))


def amazon(folder: Path):
    lines = read(folder, AMAZON)
    asins, codes, orders = defaultdict(set), defaultdict(set), defaultdict(set)
    for r in lines:
        asins[r["SKU"]].add(r["ASIN"])
        codes[r["ASIN"]].add(r["SKU"])
        orders[r["Order ID"]].add(r["SKU"])
    return lines, asins, codes, orders


def product_codes(folder: Path) -> dict[str, set[str]]:
    """Each product's code as the brand means it, from the three files that share the scheme, and
    the spellings the files give it."""
    out = defaultdict(set)
    for name, column in ((AMAZON, "SKU"), (INTERNATIONAL, "SKU"), (STOCK, "SKU Code")):
        for r in read(folder, name):
            code = r.get(column, "")
            if not junk(code) and code not in NOT_PRODUCTS:
                out[norm(code)].add(code)
    return out


QUESTIONS = (
    {"id": 1, "text": "What is the ASIN of our SKU JNE3781-KR-XXXL?", "columns": ["ASIN"]},
    {"id": 2, "text": "Which of our SKUs is Amazon's ASIN B09KXVBD7Z?", "columns": ["SKU code"]},
    {"id": 3, "text": "Which SKUs were on Amazon order 171-2644368-7969167?", "columns": ["SKU code"]},
    {"id": 4, "text": "How many Amazon orders included our SKU JNE3797-KR-L?", "columns": ["orders"]},
    {"id": 5, "text": "How many of our SKUs are listed on Amazon?", "columns": ["SKUs"]},
    {"id": 6, "text": "Under which of our SKU codes does Amazon list ASIN B08B4TP9NR?", "columns": ["SKU code"]},
)


def answers(folder: Path) -> dict[int, list]:
    lines, asins, codes, orders = amazon(folder)
    return {
        1: [[a] for a in sorted(asins.get("JNE3781-KR-XXXL", ()))],
        2: [[c] for c in sorted(codes.get("B09KXVBD7Z", ()))],
        3: [[c] for c in sorted(orders.get("171-2644368-7969167", ()))],
        4: [[len({r["Order ID"] for r in lines if r["SKU"] == "JNE3797-KR-L"})]],
        5: [[len({norm(r["SKU"]) for r in lines})]],
        6: [[c] for c in sorted(codes.get("B08B4TP9NR", ()))],
    }


def listings(conn) -> dict[str, tuple]:
    """Each Amazon listing in the store: its seller SKU, to its SKU's entity and its ASIN."""
    if not has_attr(conn, "listing/sku"):
        return {}
    sku = dict(rows(conn, 'select e, v from current."listing/sku"'))
    asin = dict(rows(conn, '''select l.e, a.v from current."listing/asin" l join current."amazon/asin" a on a.e = l.v''')) \
        if has_attr(conn, "listing/asin") else {}
    return {v: (sku.get(e), asin.get(e)) for e, v in rows(conn, 'select e, v from current."amazon/seller_sku"')}


def asin_products(conn, one) -> dict[str, set]:
    """Each ASIN in the store, to the products it reaches: through the listings under it, or, in a
    store from before ecom-ops 0.4.0, on the product itself."""
    out = defaultdict(set)
    if not has_attr(conn, "amazon/asin"):
        return out
    if has_attr(conn, "listing/asin") and has_attr(conn, "listing/sku"):
        for a, s in rows(conn, '''select a.v, s.v from current."amazon/asin" a join current."listing/asin" l on l.v = a.e
                                 join current."listing/sku" s on s.e = l.e'''):
            out[a].add(one(s))
    for e, a in rows(conn, 'select e, v from current."amazon/asin"'):
        if has_attr(conn, "sku/code") and rows(conn, 'select 1 from current."sku/code" where e = %s', e):
            out[a].add(one(e))
    return out


def truth(conn, folder: Path) -> dict:
    """The store's product list against the files. Counts only."""
    if not has_attr(conn, "sku/code"):
        return {"sku/code": 0}
    root = survivors(conn)
    one = lambda e: root.get(e, e)
    hubs = defaultdict(set)  # a code, normalized, to the entities holding it
    for e, v in rows(conn, 'select e, v from current."sku/code"'):
        hubs[norm(v)].add(one(e))
    asin_on = asin_products(conn, one)
    listed = listings(conn)
    lines, asins, codes, _ = amazon(folder)
    products = product_codes(folder)

    # ASINs: each one Amazon lists under exactly one code, and that code under no other ASIN.
    plain = [(c, a) for a, cs in codes.items() if len(cs) == 1 for c in cs if len(asins[c]) == 1]
    right = sum(1 for c, a in plain if asin_on.get(a, set()) & hubs.get(norm(c), set()))
    absent = sum(1 for c, a in plain if a not in asin_on or norm(c) not in hubs)
    # An ASIN under two codes: are both listings in the store, under it? And are the codes one
    # product there (reported only: one pair is two styles)?
    shared = {a: cs for a, cs in codes.items() if len(cs) > 1}
    both = sum(1 for a, cs in shared.items() if all(listed.get(c, (None, None))[1] == a for c in cs))
    joined = sum(1 for cs in shared.values() if len(set().union(*(hubs.get(norm(c), {None}) for c in cs)) - {None}) == 1)

    # Spellings: a product the files spell more than one way is still one product in the store.
    spelled = {n: s for n, s in products.items() if len(s) > 1}
    split = sum(1 for n in spelled if len(hubs.get(n, ())) > 1)
    raw = {v for (v,) in rows(conn, 'select v from current."sku/code"')}

    # The price lists: their codes, wherever the store put them, linked to a product of the others.
    other = {e for n in products for e in hubs.get(n, ())}
    priced = {r["Sku"] for name in PRICE_LISTS for r in read(folder, name)}
    entities_of = defaultdict(set)
    for e, v in rows(conn, "select e, v_string from cur where v_string is not null"):
        if v in priced:
            entities_of[v].add(one(e))
    return {
        "products_in_files": len(products), "products_in_store": sum(1 for n in products if n in hubs),
        "sku_codes_in_store": len(raw),
        "asins": {"plain": len(plain), "right": right, "on_another_code": len(plain) - right - absent,
                  "absent": absent},
        "asin_under_two_codes": {"in_files": len(shared), "both_listings_under_it": both, "codes_one_product": joined},
        "listings": {"seller_skus": len({r["SKU"] for r in lines}), "in_store": len(listed),
                     "without_sku": sum(1 for sku, _ in listed.values() if sku is None)},
        "spellings": {"products_spelled_two_ways": len(spelled), "split_in_store": split},
        "junk_as_codes": sum(1 for v in raw if junk(v)),
        "charges_as_codes": sum(1 for v in raw if norm(v) in {norm(x) for x in NOT_PRODUCTS}),
        "price_list": {"codes": len(priced), "in_store": len(entities_of),
                       "linked_to_other_products": sum(1 for es in entities_of.values() if es & other)},
    }
