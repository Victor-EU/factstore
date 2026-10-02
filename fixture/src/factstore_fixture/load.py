"""The direct loader: writes the simulated business into a store through transact, the way
the catalogue and ingestion skills would once they work.

The store is primary for suppliers, SKUs, POs, inspections, shipments, customs entries
and stock at factories and on the water, so those get full facts as their history
unfolds. Shopify, Amazon and the 3PL own the rest, so their records are indexed with
identifiers and join keys only (design open question 2's default). QuickBooks is the
general ledger, which the store never holds.

Every entity is addressed through an identity attribute, so loading twice changes nothing.
"""

import time
from dataclasses import dataclass, field

from factstore import Store

from .catalog import TPL
from .clock import YEAR_START, US_EAST
from .model import AmazonOrder, Event, ShopifyOrder
from .simulate import Simulation
from .vocabulary import ALL


@dataclass
class LoadStats:
    transactions: int = 0
    facts: int = 0
    sales_transactions: int = 0
    sales_facts: int = 0
    sales_seconds: float = 0.0
    seconds: float = 0.0
    orders: int = 0
    unchanged: int = 0
    timings: list = field(default_factory=list)
    marks: dict = field(default_factory=dict)


def load(store: Store, sim: Simulation, *, batch: int = 200, records: bool = True, sales: bool = True,
         max_orders: int | None = None, marks=(), progress=None) -> LoadStats:
    """Write the simulation into `store`. `records` covers master data and the supply-side history,
    `sales` this year's orders, `batch` orders to a transaction.

    The store stamps each transaction with the time it was written, not the simulated time, so
    `marks` (simulated instants) are reported in `stats.marks` as the last transaction written
    before each: what as-of reads use instead."""
    stats = LoadStats()
    started = time.perf_counter()
    if records:
        store.register_attribute(ALL)
        _write(store, stats, _master_data(sim))
    marks = sorted(marks)
    pending: list[dict] = []
    for item in sim.run():
        while marks and _when(item) >= marks[0]:
            if pending:
                _write(store, stats, pending, sales=True)
                pending = []
            stats.marks[marks.pop(0)] = _last_tx(store)
        if isinstance(item, Event):
            if records:
                _write(store, stats, _event_facts(item))
        elif sales and _this_year(item):
            if max_orders is not None and stats.orders >= max_orders:
                if not records:
                    break
                continue
            pending += _order_facts(item)
            stats.orders += 1
            if stats.orders % batch == 0:
                _write(store, stats, pending, sales=True)
                pending = []
                if progress:
                    progress(stats)
    if pending:
        _write(store, stats, pending, sales=True)
    stats.seconds = time.perf_counter() - started
    return stats


def order_batches(sim: Simulation, batch: int, max_orders: int | None = None):
    """This year's orders as lists of facts, `batch` orders each: for concurrent writers."""
    pending, n = [], 0
    for item in sim.run():
        if isinstance(item, Event) or not _this_year(item):
            continue
        pending += _order_facts(item)
        n += 1
        if n % batch == 0:
            yield pending
            pending = []
        if max_orders is not None and n >= max_orders:
            break
    if pending:
        yield pending


def _write(store: Store, stats: LoadStats, facts: list[dict], *, sales: bool = False) -> None:
    if not facts:
        return
    t = time.perf_counter()
    result = store.transact(facts)
    elapsed = time.perf_counter() - t
    if result.tx is None:
        stats.unchanged += 1
        return
    stats.transactions += 1
    stats.facts += len(result.facts) + 2  # plus the kernel's fs/actor and fs/at
    if sales:
        stats.sales_transactions += 1
        stats.sales_facts += len(result.facts) + 2
        stats.sales_seconds += elapsed
        stats.timings.append((len(result.facts), elapsed))


def _when(item):
    return item.at if isinstance(item, Event) else item.created if isinstance(item, ShopifyOrder) else item.purchased


def _this_year(order) -> bool:
    return _when(order).astimezone(US_EAST).date() >= YEAR_START


def _last_tx(store: Store) -> int:
    return store.conn.execute("select max(id) from tx").fetchone()[0]


def f(e, a, v):
    return {"e": e, "a": a, "v": v}


def po_ref(po):
    return ["po/number", po.number]


def shipment_ref(shipment):
    return ["shipment/booking_no", shipment.booking_no]


def sku_ref(sku):
    return ["sku/code", sku.code]


def _master_data(sim: Simulation) -> list[dict]:
    facts = []
    for code, name, kind in [*[(f"FAC-{s.code}", f"{s.name} (factory)", "factory") for s in sim.suppliers],
                             ("OCEAN", "On the water", "in_transit"), ("3PL-NJ", f"{TPL[0]}, {TPL[2]}", "3pl"),
                             ("FBA-US", "Amazon FBA (US)", "fba")]:
        loc = ["location/code", code]
        facts += [f(loc, "location/name", name), f(loc, "location/kind", kind)]
    for s in sim.suppliers:
        e = ["supplier/code", s.code]
        facts += [f(e, "supplier/name", s.name), f(e, "supplier/name_cn", s.name_cn),
                  f(e, "supplier/address", s.address), f(e, "supplier/port", s.port_locode),
                  f(e, "supplier/currency", s.currency), f(e, "supplier/payment_terms", s.payment_terms),
                  f(e, "supplier/incoterm", s.incoterm), f(e, "supplier/contact_name", s.sales)]
    for k in sim.skus:
        e = sku_ref(k)
        facts += [f(e, "sku/title", k.title), f(e, "sku/family", k.family.code),
                  f(e, "sku/supplier", ["supplier/code", k.supplier.code]), f(e, "sku/hs_code", k.family.hs_code),
                  f(e, "sku/upc", k.upc), f(e, "sku/retail_price", str(k.family.retail)), f(e, "core/currency", "USD"),
                  f(e, "factory/item_code", k.factory_item_key), f(e, "tpl/item_code", k.tpl_item_code),
                  f(e, "shopify/variant_id", str(k.shopify_variant_id))]
        if k.launched:
            facts.append(f(e, "sku/launched_on", k.launched.isoformat()))
        if k.asin:
            facts += [f(e, "amazon/asin", k.asin), f(e, "amazon/fnsku", k.fnsku),
                      f(e, "amazon/seller_sku", k.amazon_seller_sku)]
    return facts


def _event_facts(event: Event) -> list[dict]:
    kind, s = event.kind, event.subject
    if kind == "po.placed":
        po = po_ref(s)
        facts = [f(po, "po/supplier", ["supplier/code", s.supplier.code]),
                 f(po, "po/placed_on", s.placed.date().isoformat()), f(po, "po/status", "draft"),
                 f(po, "core/currency", s.currency)]
        for line in s.lines:
            ln = ["po_line/key", line.key]
            facts += [f(ln, "core/part_of", po), f(ln, "po_line/sku", sku_ref(line.sku)),
                      f(ln, "po_line/quantity", line.quantity)]
        return facts
    if kind == "po.status":
        return [f(po_ref(s), "po/status", event.data["status"])]
    if kind == "po.confirmed":
        po = po_ref(s)
        return [f(po, "po/pi_number", s.pi_number), f(po, "po/etd", event.data["etd"].isoformat()),
                f(po, "po/status", "confirmed")] + [
            f(["po_line/key", line.key], "po_line/unit_price", str(line.unit_price)) for line in s.lines]
    if kind == "po.etd":
        return [f(po_ref(s), "po/etd", event.data["etd"].isoformat())]
    if kind == "qc.inspected":
        e = ["qc/report_no", s.report_no]
        return [f(e, "qc/po", po_ref(s.po)), f(e, "qc/inspected_on", s.on.isoformat()), f(e, "qc/result", s.result),
                f(e, "qc/inspector", s.inspector), f(e, "qc/sample_size", s.sample_size)]
    if kind == "shipment.booked":
        e = shipment_ref(s)
        facts = [f(e, "shipment/hbl", s.hbl), f(e, "shipment/mode", s.mode), f(e, "shipment/status", "booked"),
                 f(e, "shipment/origin", s.origin), f(e, "shipment/destination", s.destination),
                 f(e, "shipment/vessel", f"{s.vessel} {s.voyage}"), f(e, "shipment/etd", s.etd.isoformat()),
                 f(e, "shipment/eta", s.eta.isoformat()), f(e, "shipment/freight_cost", str(s.freight)),
                 f(e, "core/currency", "USD")]
        if s.container_no:
            facts.append(f(e, "shipment/container_no", s.container_no))
        for n, line in enumerate(s.lines, 1):
            ln = ["shipment_line/key", f"{s.booking_no}/{n}"]
            facts += [f(ln, "core/part_of", e), f(ln, "shipment_line/po_line", ["po_line/key", line.po_line.key]),
                      f(ln, "shipment_line/quantity", line.quantity), f(ln, "shipment_line/cartons", line.cartons)]
        return facts
    if kind == "shipment.etd":
        return [f(shipment_ref(s), "shipment/etd", event.data["etd"].isoformat()),
                f(shipment_ref(s), "shipment/eta", event.data["eta"].isoformat())]
    if kind == "shipment.eta":
        return [f(shipment_ref(s), "shipment/eta", event.data["eta"].isoformat())]
    if kind in ("shipment.departed", "shipment.arrived"):
        return [f(shipment_ref(s), "shipment/status", kind.split(".")[1])]
    if kind == "shipment.delivered":
        e = shipment_ref(s)
        return [f(e, "shipment/status", "delivered"), f(e, "shipment/delivered_at", s.delivered.isoformat()),
                f(["tpl/receipt_no", s.receipt.receipt_no], "receipt/shipment", e)]
    if kind == "customs.entered":
        e = ["customs/entry_no", s.entry_no]
        return [f(e, "customs/shipment", shipment_ref(s.shipment)), f(e, "customs/filed_on", s.filed.isoformat()),
                f(e, "customs/entered_value", str(sum(ln.value_usd for ln in s.lines))),
                f(e, "customs/duty", str(s.duty)), f(e, "customs/fees", str(s.mpf + s.hmf)),
                f(e, "core/currency", "USD")]
    if kind == "fba.created":
        e = ["amazon/fba_shipment_id", s.shipment_id]
        return [fact for sku, *_ in s.lines
                for fact in (f(["amazon/fba_line", f"{s.shipment_id}/{sku.amazon_seller_sku}"], "core/part_of", e),
                             f(["amazon/fba_line", f"{s.shipment_id}/{sku.amazon_seller_sku}"], "line/sku", sku_ref(sku)))]
    if kind == "inventory.snapshot":
        facts = []
        for p in s:
            e = ["inventory/position", p.key]
            facts += [f(e, "inventory/sku", sku_ref(p.sku)), f(e, "inventory/location", ["location/code", p.location])]
            if p.location.startswith("FAC-") or p.location == "OCEAN":  # the store is primary for these
                facts += [f(e, "inventory/quantity", p.quantity), f(e, "inventory/counted_at", p.counted_at.isoformat())]
        return facts
    raise ValueError(f"no loader for {kind}")


def _order_facts(order) -> list[dict]:
    if isinstance(order, ShopifyOrder):
        e = ["shopify/order_id", str(order.id)]
        customer = ["shopify/customer_id", str(order.customer.id)]
        facts = [f(e, "order/customer", customer)]
        if order.customer.duplicate_of:  # the catalogue's identity resolution, done perfectly
            facts.append(f(customer, "core/same_as", ["shopify/customer_id", str(order.customer.duplicate_of)]))
        for line in order.lines:
            ln = ["shopify/line_item_id", str(line.id)]
            facts += [f(ln, "core/part_of", e), f(ln, "line/sku", sku_ref(line.sku))]
        return facts
    assert isinstance(order, AmazonOrder)
    e = ["amazon/order_id", order.id]
    facts = []
    for line in order.lines:
        ln = ["amazon/order_line", f"{order.id}/{line.sku.amazon_seller_sku}"]
        facts += [f(ln, "core/part_of", e), f(ln, "line/sku", sku_ref(line.sku))]
    return facts
