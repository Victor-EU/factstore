"""The ten questions (build plan M0), asked of the default fixture world, with reference answers.

They are an operator's questions about the supply side, which the store is primary for (the
open question 2 default leaves sales fields in Shopify and Amazon). Between them they need ref
traversal in both directions, aggregation, arithmetic, a transitive ref, an as-of read, the
log's history and the transaction stamps.

Reference answers come from a deliberately naive fold over the log (tests/reference.py), not
from any candidate language.
"""

import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "factstore" / "tests"))
import reference  # noqa: E402

# The last transaction the loader wrote before 1 July 2026, simulated time (setup_store.py prints it).
JULY_1_TX = 103815

QUESTIONS = [
    {"id": 1,
     "text": "What is in transit for SKU AH-KTL-0001-BLK? In transit means on a shipment whose status is "
             "departed or arrived. For each such shipment, give its booking number, status, ETA, and the "
             "total units of that SKU on it.",
     "columns": ["booking number", "status", "ETA", "units"]},
    {"id": 2,
     "text": "Which of supplier NBBW's purchase orders now have an ETD later than the ETD first recorded for "
             "them? Give the PO number, the first ETD recorded, and the current ETD.",
     "columns": ["PO number", "first ETD", "current ETD"]},
    {"id": 3,
     "text": f"As of transaction {JULY_1_TX}, the last write before 1 July 2026: which shipments had status "
             "departed or arrived, and what was each one's ETA as recorded at that point? Give the booking "
             "number, status and ETA.",
     "columns": ["booking number", "status", "ETA"]},
    {"id": 4,
     "text": "For customs entries filed from 1 April 2026 to 30 June 2026 inclusive, give the number of "
             "entries, the total entered value, the total duty and the total fees.",
     "columns": ["entries", "entered value", "duty", "fees"]},
    {"id": 5,
     "text": "For pre-shipment inspections carried out in 2026, how many were there per supplier and "
             "result? Give the supplier code, the result and the count.",
     "columns": ["supplier code", "result", "count"]},
    {"id": 6,
     "text": "For the product with ASIN B0BVUGZ3AT, give our SKU code, its Shopify variant ID, FNSKU, Amazon "
             "seller SKU, 3PL item code and factory item code, and the code of the supplier that makes it.",
     "columns": ["SKU code", "Shopify variant ID", "FNSKU", "seller SKU", "3PL item code", "factory item code",
                 "supplier code"]},
    {"id": 7,
     "text": "What is each supplier's open purchase order value? Open POs are those whose status is neither "
             "shipped nor received. Per supplier, give the supplier code, the currency, and the total of "
             "quantity times unit price over every line of its open POs.",
     "columns": ["supplier code", "currency", "value"]},
    {"id": 8,
     "text": "How many Shopify orders has the person behind Shopify customer 8995877069469 placed, counting "
             "every account recorded as the same person? Duplicate accounts point at the account they "
             "duplicate with core/same_as, sometimes through several links. Give the number of accounts and "
             "the number of orders.",
     "columns": ["accounts", "orders"]},
    {"id": 9,
     "text": "Who recorded PO-2026-0023's current ETD, in which transaction, and when? Give the actor's name, "
             "the transaction ID and the time it was recorded.",
     "columns": ["actor", "transaction", "time"]},
    {"id": 10,
     "text": "How many units of SKU AH-TWL-0007-NAT were last counted at each location whose kind is factory "
             "or in_transit? Give the location code, its kind and the quantity.",
     "columns": ["location code", "kind", "quantity"]},
]


class World:
    """The naive reader: current state, state as of a transaction, and the raw log."""

    def __init__(self, conn):
        self.conn = conn
        self.ids = dict(conn.execute("select ident, id from attr").fetchall())
        self.now = reference.state(conn)
        self.july = reference.state(conn, JULY_1_TX)
        self.log = conn.execute(
            "select e, a, coalesce(v_string, v_decimal::text, v_boolean::text, v_date::text, v_instant::text,"
            " v_ref::text), tx, op from fact order by tx").fetchall()

    def one(self, e, ident, state=None):
        vs = (state or self.now).get((e, self.ids[ident]), frozenset())
        assert len(vs) <= 1, (e, ident, vs)
        return next(iter(vs), None)

    def having(self, ident, value=None, state=None):
        a = self.ids[ident]
        return [e for (e, attr), vs in (state or self.now).items()
                if attr == a and (value is None or value in vs)]

    def lookup(self, ident, value):
        found = self.having(ident, value)
        assert len(found) == 1, (ident, value, found)
        return found[0]


def answers(w: World) -> dict[int, list[tuple]]:
    out = {}

    # 1. In transit for a SKU.
    sku = w.lookup("sku/code", "AH-KTL-0001-BLK")
    units = defaultdict(Decimal)
    for sl in w.having("shipment_line/po_line"):
        if w.one(w.one(sl, "shipment_line/po_line"), "po_line/sku") == sku:
            (s,) = w.now[(sl, w.ids["core/part_of"])]
            if w.one(s, "shipment/status") in ("departed", "arrived"):
                units[s] += w.one(sl, "shipment_line/quantity")
    out[1] = [(w.one(s, "shipment/booking_no"), w.one(s, "shipment/status"), w.one(s, "shipment/eta"), q)
              for s, q in units.items()]

    # 2. POs whose ETD moved later than first recorded.
    nbbw = w.lookup("supplier/code", "NBBW")
    first = {}
    for e, a, v, tx, op in w.log:
        if a == w.ids["po/etd"] and op and e not in first:
            first[e] = date.fromisoformat(v)
    out[2] = [(w.one(po, "po/number"), first[po], w.one(po, "po/etd"))
              for po in w.having("po/supplier", nbbw) if po in first and w.one(po, "po/etd") > first[po]]

    # 3. In transit as of 1 July.
    out[3] = [(w.one(s, "shipment/booking_no", w.july), st, w.one(s, "shipment/eta", w.july))
              for s in w.having("shipment/status", state=w.july)
              if (st := w.one(s, "shipment/status", w.july)) in ("departed", "arrived")]

    # 4. Customs entries filed in Q2.
    entries = [e for e in w.having("customs/filed_on")
               if date(2026, 4, 1) <= w.one(e, "customs/filed_on") <= date(2026, 6, 30)]
    out[4] = [(len(entries), *(sum(w.one(e, a) for e in entries)
                               for a in ("customs/entered_value", "customs/duty", "customs/fees")))]

    # 5. Inspections per supplier and result.
    counts = defaultdict(int)
    for qc in w.having("qc/inspected_on"):
        if w.one(qc, "qc/inspected_on") >= date(2026, 1, 1):
            supplier = w.one(w.one(w.one(qc, "qc/po"), "po/supplier"), "supplier/code")
            counts[(supplier, w.one(qc, "qc/result"))] += 1
    out[5] = [(*k, n) for k, n in counts.items()]

    # 6. The crosswalk for an ASIN.
    sku = w.lookup("amazon/asin", "B0BVUGZ3AT")
    out[6] = [(*(w.one(sku, a) for a in ("sku/code", "shopify/variant_id", "amazon/fnsku", "amazon/seller_sku",
                                         "tpl/item_code", "factory/item_code")),
               w.one(w.one(sku, "sku/supplier"), "supplier/code"))]

    # 7. Open PO value per supplier.
    value = defaultdict(Decimal)
    open_pos = {po for po in w.having("po/status") if w.one(po, "po/status") not in ("shipped", "received")}
    for line in w.having("po_line/key"):
        (po,) = w.now[(line, w.ids["core/part_of"])]
        if po in open_pos:
            key = (w.one(w.one(po, "po/supplier"), "supplier/code"), w.one(po, "core/currency"))
            value[key] += w.one(line, "po_line/quantity") * w.one(line, "po_line/unit_price")
    out[7] = [(*k, v) for k, v in value.items()]

    # 8. Orders across duplicate accounts.
    def root(e):
        while (nxt := w.one(e, "core/same_as")) is not None:
            e = nxt
        return e
    person = root(w.lookup("shopify/customer_id", "8995877069469"))
    accounts = [c for c in w.having("shopify/customer_id") if root(c) == person]
    orders = [o for o in w.having("order/customer") if w.one(o, "order/customer") in accounts]
    out[8] = [(len(accounts), len(orders))]

    # 9. Who recorded the current ETD, and when.
    po = w.lookup("po/number", "PO-2026-0023")
    etd = w.one(po, "po/etd")
    tx = max(t for e, a, v, t, op in w.log if e == po and a == w.ids["po/etd"] and op and v == etd.isoformat())
    out[9] = [(w.one(w.one(tx, "fs/actor"), "fs/name"), tx, w.one(tx, "fs/at"))]

    # 10. Stock at factories and on the water.
    sku = w.lookup("sku/code", "AH-TWL-0007-NAT")
    out[10] = [(w.one(loc, "location/code"), kind, w.one(p, "inventory/quantity"))
               for p in w.having("inventory/sku", sku)
               if (kind := w.one(loc := w.one(p, "inventory/location"), "location/kind")) in ("factory", "in_transit")]
    return out


if __name__ == "__main__":
    import json

    import psycopg

    store = json.load(open(Path(__file__).with_name("store.json")))
    with psycopg.connect(store["dsn"]) as conn:
        for qid, rows in answers(World(conn)).items():
            print(qid, sorted(rows, key=str))
