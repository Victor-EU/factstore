"""The simulation behaves like the business it imitates. Each test is a fact an operator
of such a brand would recognise; the bounds are deliberately loose."""

from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from factstore_fixture import ids
from factstore_fixture.catalog import Sku
from factstore_fixture.clock import FACTORY_CLOSED, US_EAST, YEAR_START
from factstore_fixture.model import AmazonOrder, Event, ShopifyOrder
from factstore_fixture.simulate import Simulation


def orders(items, kind):
    return [i for i in items if isinstance(i, kind)]


def day(order):
    when = order.created if isinstance(order, ShopifyOrder) else order.purchased
    return when.astimezone(US_EAST).date()


def test_check_digits_are_real():
    assert ids.iso6346("CSQ", 305438) == "CSQU3054383"   # the standard's worked example
    assert ids.upc_a("0360002914", 5) == "036000291452"     # a well-known UPC-A


def test_the_world_is_deterministic(world):
    sim, items = world
    again = Simulation(7)
    first = [(type(i).__name__, getattr(i, "id", None) or getattr(i, "kind", None)) for i in again.run()]
    assert first == [(type(i).__name__, getattr(i, "id", None) or getattr(i, "kind", None)) for i in items]


def test_stock_never_goes_negative(world):
    sim, _ = world
    for location, stock in sim.stock.items():
        assert min(stock.values()) >= 0, location


def test_seasonality_and_retail_events(world):
    _, items = world
    shopify = Counter(day(o).month for o in orders(items, ShopifyOrder) if day(o) >= YEAR_START)
    assert shopify[5] > shopify[2] * 1.4                       # Mother's Day month against February
    amazon = Counter(day(o) for o in orders(items, AmazonOrder))
    prime = sum(amazon[date(2026, 7, d)] for d in range(7, 11))
    week_before = sum(amazon[date(2026, 6, d)] for d in range(23, 27))
    assert prime > 2 * week_before                              # Prime Day


def test_customers_come_back_and_some_sign_up_twice(world):
    sim, items = world
    placed = [o for o in orders(items, ShopifyOrder) if day(o) >= YEAR_START]
    returning = sum(1 for o in placed if o.customer.created < o.created) / len(placed)
    assert 0.15 < returning < 0.4
    assert any(c.duplicate_of for c in sim.customers)


def test_factories_follow_chinas_calendar(world):
    sim, _ = world
    for po in sim.pos:
        if po.pi_date:
            assert not any(a <= po.pi_date <= b for a, b in FACTORY_CLOSED), po.number
    january = [p for p in sim.pos if p.pi_date and date(2025, 12, 15) <= p.pi_date <= date(2026, 1, 25)]
    assert january and all(p.status != "draft" for p in january)
    # Production spanning Chinese New Year takes longer than the quote assumed.
    affected = [p for p in january if p.ready]
    assert median((p.ready - p.pi_date).days for p in affected) > 50


def test_purchasing_lead_times_and_slips(world):
    sim, _ = world
    received = [p for p in sim.pos if p.status == "received"]
    lead = [(max(s.delivered for s in p.shipments).date() - p.placed.date()).days for p in received]
    assert 70 <= median(lead) <= 130
    delayed = [p for p in sim.pos if sum(1 for s in sim.statements if s.subject == p.number
                                         and s.field == "etd" and s.source == "wechat") > 1]
    assert 0.2 < len(delayed) / len(sim.pos) < 0.7


def test_containers_and_freight(world):
    sim, _ = world
    capacity = {"40HQ": Decimal(68), "20GP": Decimal(33)}
    for s in sim.shipments:
        if s.container_no:
            assert ids.iso6346(s.container_no[:3], int(s.container_no[4:10])) == s.container_no
            assert s.cbm <= capacity[s.mode]
    modes = Counter(s.mode for s in sim.shipments)
    assert modes["LCL"] and (modes["40HQ"] + modes["20GP"]) / len(sim.shipments) > 0.3


def test_duty_reflects_china_tariffs(world):
    sim, _ = world
    rates = [e.duty / sum(ln.value_usd for ln in e.lines) for e in sim.entries]
    assert all(Decimal("0.15") < r < Decimal("0.5") for r in rates)


def test_inventory_snapshot_is_consistent(world):
    sim, items = world
    snapshot = next(i for i in items if isinstance(i, Event) and i.kind == "inventory.snapshot")
    on_water = sum(p.quantity for p in snapshot.subject if p.location == "OCEAN")
    assert on_water == sum(sl.quantity for s in sim.shipments if s.status in ("departed", "arrived") for sl in s.lines)
    assert all(isinstance(p.sku, Sku) and p.quantity > 0 for p in snapshot.subject)


def test_messy_identifiers_exist_for_the_crosswalk(world):
    sim, _ = world
    assert any(k.shopify_variant_sku != k.code for k in sim.skus)
    assert any(k.tpl_client_sku == "" for k in sim.skus) and any(k.tpl_client_sku not in ("", k.code) for k in sim.skus)
    codes = Counter(k.factory_code for k in sim.skus)
    assert any(n > 1 for n in codes.values()), "factory codes should repeat across factories"
    assert len({k.factory_item_key for k in sim.skus}) == len(sim.skus)


def test_events_come_in_time_order(world):
    """Events are emitted as the clock reaches them; a few are stamped hours after the moment
    that produced them (a report written up that afternoon), never days."""
    _, items = world
    events = [i.at for i in items if isinstance(i, Event)]
    assert not any(b < a - timedelta(days=1) for a, b in zip(events, events[1:]))
