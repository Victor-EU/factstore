"""The ten questions (build plan M0): an operator's questions about the default world, with
reference answers and reference SQL.

They are about the supply side, which the store is primary for (the open question 2 default
leaves sales fields in Shopify and Amazon). Between them they need ref traversal in both
directions, aggregation, arithmetic, a transitive ref, an as-of read, the log's history and
the transaction stamps. The OQ1 spike (spike/oq1) chose the query language with them; M2's
exit tests answer them through `query`.

Reference answers come from a deliberately naive fold over the log, not from the views or any
query language. Question 3 reads as of the last transaction before 1 July 2026 (simulated
time), which the loader reports as a mark: format its text with july_1=<that transaction>.
"""

from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal

from .clock import US_EAST

JULY_1_MARK = datetime(2026, 7, 1, tzinfo=US_EAST)

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
     "text": "As of transaction {july_1}, the last write before 1 July 2026: which shipments had status "
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
     "text": "How many units of SKU AH-TWL-0007-NAT are at factories, and how many on the water? Nothing counts "
             "them: at a factory are the units on lines of POs whose status is in_production or ready, less "
             "those on shipments that have departed (status departed, arrived or delivered). On the water are "
             "the units on shipments whose status is departed or arrived. Give one row per supplier with units "
             "at its factory, as the supplier code and the units, and one row 'on the water' with its units.",
     "columns": ["supplier code or on the water", "units"]},
]


def fold(conn, as_of=None) -> dict:
    """{(entity, attribute): values} after every transaction up to as_of: the naive reader."""
    rows = conn.execute(
        "select e, a, v_string, v_decimal, v_boolean, v_date, v_instant, v_ref, op from fact"
        " where %(t)s::bigint is null or tx <= %(t)s order by tx", {"t": as_of}).fetchall()
    values = defaultdict(set)
    for e, a, *cols, op in rows:
        v = next(c for c in cols if c is not None)
        (values[(e, a)].add if op else values[(e, a)].discard)(v)
    return {k: frozenset(vs) for k, vs in values.items() if vs}


class World:
    """The naive reader: current state, state as of a transaction, and the raw log."""

    def __init__(self, conn, july_1: int):
        self.conn = conn
        self.ids = dict(conn.execute("select ident, id from attr").fetchall())
        self.now = fold(conn)
        self.july = fold(conn, july_1)
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

    # 6. The crosswalk for an ASIN, through the Amazon listing under it.
    out[6] = []
    for listing in w.having("listing/asin", w.lookup("amazon/asin", "B0BVUGZ3AT")):
        sku = w.one(listing, "listing/sku")
        out[6].append((*(w.one(sku, a) for a in ("sku/code", "shopify/variant_id")),
                       *(w.one(listing, a) for a in ("amazon/fnsku", "amazon/seller_sku")),
                       *(w.one(sku, a) for a in ("tpl/item_code", "factory/item_code")),
                       w.one(w.one(sku, "sku/supplier"), "supplier/code")))

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

    # 10. Stock at factories and on the water, derived from POs and shipments (design §14).
    sku = w.lookup("sku/code", "AH-TWL-0007-NAT")
    sailed, water = defaultdict(Decimal), Decimal(0)
    for sl in w.having("shipment_line/po_line"):
        (s,) = w.now[(sl, w.ids["core/part_of"])]
        status, line = w.one(s, "shipment/status"), w.one(sl, "shipment_line/po_line")
        if status in ("departed", "arrived", "delivered"):
            sailed[line] += w.one(sl, "shipment_line/quantity")
        if status in ("departed", "arrived") and w.one(line, "po_line/sku") == sku:
            water += w.one(sl, "shipment_line/quantity")
    factory = defaultdict(Decimal)
    for line in w.having("po_line/sku", sku):
        (po,) = w.now[(line, w.ids["core/part_of"])]
        if w.one(po, "po/status") in ("in_production", "ready"):
            factory[w.one(w.one(po, "po/supplier"), "supplier/code")] += w.one(line, "po_line/quantity") - sailed[line]
    out[10] = [(code, n) for code, n in factory.items() if n > 0] + ([("on the water", water)] if water > 0 else [])
    return out



REFERENCE_SQL = {
    1: ("""
select b.v, st.v, eta.v, sum(q.v)
from "sku/code" k
join "po_line/sku" pl on pl.v = k.e
join "shipment_line/po_line" sl on sl.v = pl.e
join "shipment_line/quantity" q on q.e = sl.e
join "core/part_of" p on p.e = sl.e
join "shipment/status" st on st.e = p.v
join "shipment/booking_no" b on b.e = p.v
join "shipment/eta" eta on eta.e = p.v
where k.v = 'AH-KTL-0001-BLK' and st.v in ('departed', 'arrived')
group by 1, 2, 3""", None),
    2: ("""
with first as (
  select distinct on (e) e, v from history."po/etd" where op = 'assert' order by e, tx)
select n.v, first.v, etd.v
from "supplier/code" s
join "po/supplier" ps on ps.v = s.e
join "po/number" n on n.e = ps.e
join "po/etd" etd on etd.e = ps.e
join first on first.e = ps.e
where s.v = 'NBBW' and etd.v > first.v""", None),
    3: ("""
select b.v, st.v, eta.v
from "shipment/status" st
join "shipment/booking_no" b using (e)
join "shipment/eta" eta using (e)
where st.v in ('departed', 'arrived')""", "july_1"),
    4: ("""
select count(*), sum(ev.v), sum(d.v), sum(f.v)
from "customs/filed_on" filed
join "customs/entered_value" ev using (e)
join "customs/duty" d using (e)
join "customs/fees" f using (e)
where filed.v between '2026-04-01' and '2026-06-30'""", None),
    5: ("""
select s.v, r.v, count(*)
from "qc/inspected_on" d
join "qc/result" r using (e)
join "qc/po" qp using (e)
join "po/supplier" ps on ps.e = qp.v
join "supplier/code" s on s.e = ps.v
where d.v >= '2026-01-01'
group by 1, 2""", None),
    6: ("""
select k.v, sv.v, fn.v, ss.v, tpl.v, fac.v, sup.v
from "amazon/asin" asin
join "listing/asin" la on la.v = asin.e
join "listing/sku" ls on ls.e = la.e
join "amazon/fnsku" fn on fn.e = la.e
join "amazon/seller_sku" ss on ss.e = la.e
join "sku/code" k on k.e = ls.v
join "shopify/variant_id" sv on sv.e = k.e
join "tpl/item_code" tpl on tpl.e = k.e
join "factory/item_code" fac on fac.e = k.e
join "sku/supplier" ks on ks.e = k.e
join "supplier/code" sup on sup.e = ks.v
where asin.v = 'B0BVUGZ3AT'""", None),
    7: ("""
select s.v, cur.v, sum(q.v * p.v)
from "po/status" st
join "po/supplier" ps using (e)
join "supplier/code" s on s.e = ps.v
join "core/currency" cur on cur.e = st.e
join "core/part_of" line on line.v = st.e
join "po_line/quantity" q on q.e = line.e
join "po_line/unit_price" p on p.e = line.e
where st.v not in ('shipped', 'received')
group by 1, 2""", None),
    8: ("""
with recursive up(e) as (
  select e from "shopify/customer_id" where v = '8995877069469'
  union
  select s.v from up join "core/same_as" s on s.e = up.e
),
root as (select e from up where e not in (select e from "core/same_as")),
down(e) as (
  select e from root
  union
  select s.e from down join "core/same_as" s on s.v = down.e
)
select count(distinct down.e), count(o.e)
from down left join "order/customer" o on o.v = down.e""", None),
    9: ("""
select name.v, etd.tx, at.v
from "po/number" n
join "po/etd" etd using (e)
join "fs/actor" actor on actor.e = etd.tx
join "fs/name" name on name.e = actor.v
join "fs/at" at on at.e = etd.tx
where n.v = 'PO-2026-0023'""", None),
    10: ("""
with sailed as (
  select pl.v as po_line, sum(q.v) as units
  from "shipment_line/po_line" pl
  join "shipment_line/quantity" q on q.e = pl.e
  join "core/part_of" p on p.e = pl.e
  join "shipment/status" st on st.e = p.v
  where st.v in ('departed', 'arrived', 'delivered')
  group by 1),
factory as (
  select sc.v as place, sum(lq.v - coalesce(s.units, 0)) as units
  from "sku/code" k
  join "po_line/sku" ls on ls.v = k.e
  join "po_line/quantity" lq on lq.e = ls.e
  join "core/part_of" lp on lp.e = ls.e
  join "po/status" ps on ps.e = lp.v
  join "po/supplier" sup on sup.e = lp.v
  join "supplier/code" sc on sc.e = sup.v
  left join sailed s on s.po_line = ls.e
  where k.v = 'AH-TWL-0007-NAT' and ps.v in ('in_production', 'ready')
  group by 1),
water as (
  select 'on the water' as place, sum(q.v) as units
  from "sku/code" k
  join "po_line/sku" ls on ls.v = k.e
  join "shipment_line/po_line" pl on pl.v = ls.e
  join "shipment_line/quantity" q on q.e = pl.e
  join "core/part_of" p on p.e = pl.e
  join "shipment/status" st on st.e = p.v
  where k.v = 'AH-TWL-0007-NAT' and st.v in ('departed', 'arrived'))
select place, units from factory where units > 0
union all
select place, units from water where units > 0""", None),
}
