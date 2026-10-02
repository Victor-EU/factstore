"""The business, day by day, from July 2025 to the morning of 1 October 2026.

Demand follows the retail calendar. Each Monday the buyer reviews stock against a
forecast and places POs. Factories quote optimistically, work to China's calendar, slip
and fail inspections. The forwarder consolidates cargo onto weekly sailings, bookings
get rolled, ships run late. The broker enters goods and duty is paid. The 3PL receives
with breakage, ships Shopify orders and sends stock on to Amazon. Sales stop when stock
runs out.

Everything is seeded and deterministic. Demand scales with `scale`, and so do the POs
placed to meet it.
"""

import dataclasses
import heapq
import math
import random
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from . import catalog, ids, people
from .catalog import BROKER, FORWARDER, TPL, Sku, Supplier
from .clock import (BASE_ORDERS_PER_DAY, CHINA, HOUR_WEIGHTS, NOW, PORTS, SAILINGS, SIM_START, TODAY, US_EAST,
                    US_WEST, UTC, VESSELS, YEAR_START, add_factory_days, add_us_business_days, at, cny_per_usd,
                    demand_factor, factory_capacity, next_sailing, promotion)
from .model import (AmazonLine, AmazonOrder, Bill, CustomsEntry, Customer, Document, Email, EntryLine, Event,
                    FbaShipment, InventoryPosition, Message, Po, PoLine, QcInspection, Receipt, ReceiptLine, Shipment,
                    ShipmentLine, ShopifyLine, ShopifyOrder, Statement)

CENT = Decimal("0.01")
LINES_PER_ORDER = {"shopify": 1.45, "amazon": 1.13}
UNITS_PER_LINE = {"shopify": 1.3, "amazon": 1.11}
LOCATION = {"shopify": "3PL-NJ", "amazon": "FBA-US"}
AFFINITY = {"MUG": ("PLT", "BWL"), "PLT": ("BWL", "MUG"), "BWL": ("PLT", "MUG"), "KTL": ("TWL", "MIT"),
            "SAU": ("CSR", "SPT"), "CSR": ("SAU", "MIT"), "CTB": ("UTN", "TRY"), "UTN": ("CTB", "SPT"),
            "JAR": ("CNR", "LID"), "CNR": ("JAR",), "SPT": ("BMT",), "BMT": ("SPT",), "TPT": ("MUG",),
            "EKT": ("MUG", "TPT"), "TMB": ("BTL",), "BTL": ("TMB", "LBX"), "TWL": ("APR", "MIT")}
NEXUS_FREE_STATES = {"OR"}
MIN_ORDER_USD = 12_000
FULFILMENT_CENTRES = ["ABE8", "TEB9", "AVP1", "EWR4", "ACY2", "MDT1"]
PI_FORMATS = {"NBBW": "MT{d:%y%m%d}-{n:02d}", "SZHT": "HT-PI-{d:%Y}-{n:03d}", "YWLX": "LX{d:%y}{n:03d}",
              "DGRF": "RF-PI{d:%y}{n:03d}", "FSMJ": "MJ{d:%Y}{n:03d}", "XMYD": "YD-{d:%y}-{n:03d}",
              "NBQS": "QS{d:%y%m}{n:02d}", "HZTY": "TY-{d:%y%m%d}"}
QC_FAIL = {"MUG": 0.14, "PLT": 0.14, "BWL": 0.14, "JAR": 0.12, "TPT": 0.12, "CNR": 0.12, "KTL": 0.08, "SAU": 0.08,
           "CSR": 0.08}
DEFECTS = {
    "MUG": ["glaze pinholes", "black specks in glaze", "uneven rim", "colour variation vs approved sample"],
    "PLT": ["glaze pinholes", "warped base", "colour variation vs approved sample"],
    "BWL": ["glaze pinholes", "uneven rim", "crazing"],
    "JAR": ["bubbles in glass", "lid does not seal", "scratches"],
    "TPT": ["bubbles in glass", "spout chipped", "strainer loose"],
    "CNR": ["bubbles in glass", "gasket missing"],
    "KTL": ["enamel chipped at handle", "dent on body", "lid wobbles"],
    "SAU": ["enamel chipped at rim", "handle rivet loose"],
    "CSR": ["enamel chipped at rim", "lid misfit"],
}
GENERIC_DEFECTS = ["carton shipping marks missing", "barcode label unreadable", "polybag warning text missing",
                   "loose threads", "dirty marks"]
SLIP_REASONS = [("glaze line backlog", "釉线排不过来"), ("packaging arrived late", "包装材料晚到了"),
                ("QC rework on a batch", "有一批返工"), ("power rationing at the factory", "工厂限电"),
                ("waiting on raw material", "原材料还没到"), ("workers not all back after the holiday", "节后工人还没到齐")]


def poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam < 40:
        limit, k, p = math.exp(-lam), 0, 1.0
        while True:
            p *= rng.random()
            if p <= limit:
                return k
            k += 1
    return max(0, round(rng.gauss(lam, math.sqrt(lam))))


def money(x) -> Decimal:
    return Decimal(x).quantize(CENT)


class Simulation:
    def __init__(self, seed: int = 7, scale: float = 1.0, *, keep_outbound: bool = True):
        self.seed = seed
        self.scale = scale
        self.keep_outbound = keep_outbound  # the 3PL's per-order shipping log, which only the exports need
        self.rng = random.Random(f"{seed}:sim")
        self.skus = catalog.build(seed)
        self.suppliers = catalog.SUPPLIERS
        self.by_supplier = {s.code: [k for k in self.skus if k.supplier is s] for s in self.suppliers}
        self.amazon_price = {k.code: money(k.family.retail * Decimal(str(round(self.rng.uniform(0.95, 1.05), 2))))
                             for k in self.skus if k.asin}

        self.stock = {"3PL-NJ": defaultdict(int), "FBA-US": defaultdict(int)}
        self.fba_inbound: dict[str, int] = defaultdict(int)
        self.on_order: dict[str, int] = defaultdict(int)
        self.lost_sales: dict[str, int] = defaultdict(int)

        self.pos: list[Po] = []
        self.shipments: list[Shipment] = []
        self.entries: list[CustomsEntry] = []
        self.receipts: list[Receipt] = []
        self.fba_shipments: list[FbaShipment] = []
        self.bills: list[Bill] = []
        self.messages: list[Message] = []
        self.emails: list[Email] = []
        self.documents: list[Document] = []
        self.statements: list[Statement] = []
        self.customers: list[Customer] = []
        self.inventory: list[InventoryPosition] = []
        self.outbound: list[tuple] = []          # 3PL shipments: (when, reference, sku, quantity, carrier)
        self.counts = defaultdict(int)

        self._heap: list = []
        self._seq = 0
        self._out: list = []
        self._groups: dict[tuple, list] = {}
        self._last_po: dict[str, date] = {}
        self._po_seq = {2025: 142, 2026: 0}
        self._pi_seq: dict[str, int] = defaultdict(int)
        self._n = defaultdict(int)               # counters for IDs
        self._emails: set[str] = set()           # shoppers' addresses given out: one person each
        self._share_cache: dict = {}
        self._month = defaultdict(lambda: defaultdict(int))
        self._customer_id = 8_812_400_000_000
        self._order_id = 6_402_100_000_000
        self._order_number = 18_300
        self._line_id = 16_105_000_000_000
        self._factor = {c: {} for c in BASE_ORDERS_PER_DAY}

    # --- the clock ----------------------------------------------------------------------

    def run(self):
        """Everything that happens, in time order: Events for the store's own records, and orders."""
        self._open()
        d = SIM_START
        while d <= TODAY:
            day_end = min(at(d + timedelta(days=1), 0, US_EAST), NOW)
            self._schedule_day(d)
            if d < YEAR_START:
                yield from self._until(at(d, 12, US_EAST))
                self._aggregate_sales(d)
            else:
                for when, kind, who in self._draw_orders(d):
                    if when > day_end:
                        break
                    yield from self._until(when)
                    order = self._shopify_order(when, who) if kind == "shopify" else self._amazon_order(when, who)
                    if order is not None:
                        yield order
            yield from self._until(day_end)
            d += timedelta(days=1)
        self._snapshot()
        yield from self._flush()

    def _schedule(self, when: datetime, fn, *args) -> None:
        self._seq += 1
        heapq.heappush(self._heap, (when, self._seq, fn, args))

    def _until(self, when: datetime):
        while self._heap and self._heap[0][0] <= when:
            moment, _, fn, args = heapq.heappop(self._heap)
            fn(moment, *args)
        yield from self._flush()

    def _flush(self):
        out, self._out = self._out, []
        yield from out

    def _event(self, when: datetime, kind: str, subject, **data) -> None:
        self._out.append(Event(when, kind, subject, data))

    def _schedule_day(self, d: date) -> None:
        if d.weekday() == 0:
            self._schedule(at(d, 9, US_EAST), self._review)
        if d.weekday() == 3:
            self._schedule(at(d, 10, US_EAST), self._replenish_fba)
        if d.day == 1 and d > SIM_START:
            self._schedule(at(d, 8, US_EAST), self._tpl_invoice)
        if d == date(2026, 1, 16):
            self._schedule(at(d, 9, CHINA), self._holiday_notices, "cny")
        if d == date(2026, 9, 21):
            self._schedule(at(d, 10, CHINA), self._holiday_notices, "golden_week")
        for supplier in self.suppliers:
            for change in supplier.price_changes:
                if change.announced == d:
                    self._schedule(at(d, 10, CHINA, 12), self._price_notice, supplier, change)
        if d == YEAR_START:
            self._seed_customers()
        if self.rng.random() < 0.18:
            supplier = self.rng.choice(self.suppliers)
            self._schedule(at(d, self.rng.randint(8, 20), CHINA, self.rng.randint(0, 59)), self._small_talk, supplier)

    # --- demand -------------------------------------------------------------------------

    def _active(self, d: date, channel: str) -> list[Sku]:
        return [k for k in self.skus if (not k.launched or k.launched <= d) and (channel == "shopify" or k.asin)]

    def _shares(self, d: date, channel: str):
        cached = self._share_cache.get((channel, d))
        if cached:
            return cached
        active = self._active(d, channel)
        key = (channel, tuple(k.code for k in active))
        if key not in self._share_cache:
            total = sum(k.popularity for k in active)
            cumulative, acc = [], 0.0
            for k in active:
                acc += k.popularity
                cumulative.append(acc)
            self._share_cache[key] = (active, {k.code: k.popularity / total for k in active}, cumulative)
        self._share_cache[(channel, d)] = self._share_cache[key]
        return self._share_cache[key]

    def _daily_factor(self, d: date, channel: str) -> float:
        cache = self._factor[channel]
        if d not in cache:
            cache[d] = demand_factor(d, channel)
        return cache[d]

    def expected_units(self, sku: Sku, d: date, channel: str) -> float:
        if channel == "amazon" and not sku.asin:
            return 0.0
        share = self._shares(max(d, sku.launched or d), channel)[1].get(sku.code, 0.0)
        return (BASE_ORDERS_PER_DAY[channel] * self.scale * self._daily_factor(d, channel)
                * LINES_PER_ORDER[channel] * UNITS_PER_LINE[channel] * share)

    def forecast(self, sku: Sku, start: date, days: int, channels=("shopify", "amazon")) -> float:
        total, step = 0.0, 3
        for i in range(0, days, step):
            d = start + timedelta(days=i)
            if sku.launched and d < sku.launched:
                continue
            total += step * sum(self.expected_units(sku, d, c) for c in channels)
        return total

    def _aggregate_sales(self, d: date) -> None:
        """Before the year starts only stock matters, so sales are drawn per SKU, not per order."""
        for channel in ("shopify", "amazon"):
            stock = self.stock[LOCATION[channel]]
            for sku in self._active(d, channel):
                units = poisson(self.rng, self.expected_units(sku, d, channel))
                sold = min(units, stock[sku.code])
                stock[sku.code] -= sold
                self.lost_sales[sku.code] += units - sold
                if channel == "shopify" and sold:
                    self._month[d.strftime("%Y-%m")]["orders"] += max(1, round(sold / 1.88))
                    self._month[d.strftime("%Y-%m")]["units"] += sold

    def _draw_orders(self, d: date) -> list:
        orders = []
        for channel in ("shopify", "amazon"):
            n = poisson(self.rng, BASE_ORDERS_PER_DAY[channel] * self.scale * self._daily_factor(d, channel))
            for _ in range(n):
                if channel == "shopify" and self.customers and self.rng.random() < 0.26:
                    i = int(len(self.customers) * (1 - self.rng.random() ** 2.2))
                    who = self.customers[min(i, len(self.customers) - 1)]
                    tz = who.person.tz
                else:
                    who = people.person(self.rng, self._n["person"], self._emails)
                    self._n["person"] += 1
                    tz = who.tz
                hour = self.rng.choices(range(24), weights=HOUR_WEIGHTS)[0]
                local = at(d, hour, tz, self.rng.randint(0, 59)) + timedelta(seconds=self.rng.randint(0, 59))
                orders.append((local.astimezone(UTC), channel, who))
        orders.sort(key=lambda o: o[0])
        return orders

    def _pick(self, d: date, channel: str, n_lines: int) -> list[Sku]:
        active, _, cumulative = self._shares(d, channel)
        first = self.rng.choices(active, cum_weights=cumulative)[0]
        chosen = [first]
        for _ in range(n_lines * 4):
            if len(chosen) >= n_lines:
                break
            base = self.rng.choice(chosen)
            partners = [k for k in active if k.family.code in AFFINITY.get(base.family.code, ())
                        or (k.family is base.family and k is not base)]
            if partners and self.rng.random() < 0.45:
                chosen.append(self.rng.choice(partners))
            else:
                chosen.append(self.rng.choices(active, cum_weights=cumulative)[0])
            chosen = list(dict.fromkeys(chosen))
        return chosen

    def _shopify_order(self, when: datetime, who) -> ShopifyOrder | None:
        rng, d = self.rng, when.astimezone(US_EAST).date()
        stock = self.stock["3PL-NJ"]
        n_lines = rng.choices([1, 2, 3, 4], weights=[68, 22, 7, 3])[0]
        lines = []
        for sku in self._pick(d, "shopify", n_lines):
            if sku.family.code in ("MUG", "PLT", "BWL"):
                qty = rng.choices([1, 2, 4, 6], weights=[45, 25, 25, 5])[0]
            else:
                qty = rng.choices([1, 2, 3], weights=[88, 10, 2])[0]
            if stock[sku.code] < qty:
                self.lost_sales[sku.code] += qty
                continue
            lines.append((sku, qty))
        if not lines:
            return None

        if isinstance(who, Customer):
            customer, new = who, False
        else:
            duplicate_of = None
            if self.customers and rng.random() < 0.015:  # a past customer signing up again
                original = rng.choice(self.customers)
                who = dataclasses.replace(original.person,
                                          email=people.alias_email(rng, original.person.email, self._emails))
                duplicate_of = original.id
            self._customer_id += rng.randint(2_000_000, 40_000_000)
            customer = Customer(self._customer_id, who, when, duplicate_of)
            self.customers.append(customer)
            new = True
        address = customer.person if rng.random() > 0.06 else people.person(rng, self._n["person"] + 10**7)

        code, percent = promotion(d)
        if not (code and rng.random() < 0.45):
            code, percent = ("WELCOME10", 10) if new and rng.random() < 0.2 else (None, 0)
        self._order_id += rng.randint(500_000, 20_000_000)
        self._order_number += 1
        shopify_lines = []
        for sku, qty in lines:
            self._line_id += rng.randint(100_000, 5_000_000)
            discount = money(sku.family.retail * qty * percent / 100)
            shopify_lines.append(ShopifyLine(self._line_id, sku, qty, sku.family.retail, discount))
        subtotal = sum((ln.price * ln.quantity - ln.discount for ln in shopify_lines), Decimal(0))
        expedited = rng.random() < 0.07
        shipping = Decimal("14.95") if expedited else (Decimal(0) if subtotal >= 75 else Decimal("6.95"))
        tax = Decimal(0) if address.state in NEXUS_FREE_STATES else money(subtotal * address.tax_rate)
        source = rng.choices(["web", "shop_app", "instagram", "shopify_draft_order"], weights=[86, 9, 4, 1])[0]
        order = ShopifyOrder(self._order_id, self._order_number, when, customer, address, shopify_lines, code,
                             shipping, "Expedited" if expedited else "Standard", tax, source, None)

        if rng.random() < 0.011:
            order.cancelled = when + timedelta(hours=rng.randint(1, 20))
            order.cancel_reason = rng.choices(["customer", "fraud", "inventory"], weights=[70, 15, 15])[0]
            return order
        for sku, qty in lines:
            stock[sku.code] -= qty
        ship_day = add_us_business_days(d, rng.choice([1, 1, 2]))
        order.fulfilled = at(ship_day, rng.randint(13, 18), US_EAST, rng.randint(0, 59))
        carrier = "UPS Ground" if expedited or subtotal > 60 else rng.choice(["USPS Ground Advantage", "UPS Ground"])
        if self.keep_outbound:
            self.outbound.append((order.fulfilled, order.name, lines, carrier))
        month = d.strftime("%Y-%m")
        self._month[month]["orders"] += 1
        self._month[month]["units"] += sum(q for _, q in lines)
        roll = rng.random()
        if roll < 0.032:
            refunded = order.fulfilled + timedelta(days=rng.randint(8, 30))
            order.refunds.append((refunded, order.total))
            if rng.random() < 0.55:
                self._schedule(refunded + timedelta(days=5), self._restock, lines)
        elif roll < 0.045 and any(k.family.damage_rate >= 0.012 for k, _ in lines):
            broken = next(ln for ln in shopify_lines if ln.sku.family.damage_rate >= 0.012)
            order.refunds.append((order.fulfilled + timedelta(days=rng.randint(3, 7)), broken.price))
        return order

    def _amazon_order(self, when: datetime, who) -> AmazonOrder | None:
        rng, d = self.rng, when.astimezone(US_EAST).date()
        stock = self.stock["FBA-US"]
        n_lines = rng.choices([1, 2, 3], weights=[88, 10, 2])[0]
        prime_day = date(2026, 7, 7) <= d <= date(2026, 7, 10)
        top = sorted(self._active(d, "amazon"), key=lambda k: -k.popularity)[:6]
        lines = []
        for sku in self._pick(d, "amazon", n_lines):
            qty = rng.choices([1, 2, 3], weights=[90, 8, 2])[0]
            if stock[sku.code] < qty:
                self.lost_sales[sku.code] += qty
                continue
            price = self.amazon_price[sku.code] * qty
            promo, promo_id = Decimal(0), None
            if prime_day and sku in top:
                promo, promo_id = money(price * Decimal("0.25")), "Prime Day Deal"
            elif promotion(d)[0] and rng.random() < 0.25:
                promo, promo_id = money(price * Decimal("0.10")), "Save 10% coupon"
            tax = Decimal(0) if who.state in NEXUS_FREE_STATES else money((price - promo) * who.tax_rate)
            lines.append(AmazonLine(sku, qty, money(price), tax, promo, promo_id))
        if not lines:
            return None
        order = AmazonOrder(ids.amazon_order_id(rng), when, lines,
                            who.city.upper() if rng.random() < 0.6 else who.city, who.state, who.zip,
                            rng.choices(["Expedited", "Standard", "SecondDay", "NextDay"], weights=[70, 25, 4, 1])[0],
                            when + timedelta(hours=rng.randint(4, 30)))
        if rng.random() < 0.008:
            order.cancelled, order.shipped = True, None
            return order
        for line in lines:
            stock[line.sku.code] -= line.quantity
        return order

    def _restock(self, when: datetime, lines) -> None:
        for sku, qty in lines:
            self.stock["3PL-NJ"][sku.code] += qty

    # --- purchasing ---------------------------------------------------------------------

    def _open(self) -> None:
        """Stock on hand when the simulation starts: about four months' worth."""
        for sku in self.skus:
            if sku.launched:
                continue
            self.stock["3PL-NJ"][sku.code] = round(self.forecast(sku, SIM_START, 120, ("shopify",))
                                                   + self.forecast(sku, SIM_START, 25, ("amazon",)))
            if sku.asin:
                self.stock["FBA-US"][sku.code] = round(self.forecast(sku, SIM_START, 70, ("amazon",)))

    def _position(self, sku: Sku) -> int:
        return (self.stock["3PL-NJ"][sku.code] + self.stock["FBA-US"][sku.code] + self.fba_inbound[sku.code]
                + self.on_order[sku.code])

    def _lead_days(self, supplier: Supplier, d: date) -> int:
        days = sum(k.family.production_days for k in self.by_supplier[supplier.code]) / len(self.by_supplier[supplier.code])
        ready = add_factory_days(d + timedelta(days=8), days * 1.1)
        return (ready - d).days + 7 + 33 + 6

    def _review(self, now: datetime) -> None:
        """Weekly stock review. A supplier that needs a PO pulls forward the others on the same port,
        so their goods can share a container."""
        d = now.date()
        triggered, wanted = set(), {}
        for supplier in self.suppliers:
            last = self._last_po.get(supplier.code)
            if last and (d - last).days < 42:
                continue
            lead = self._lead_days(supplier, d)
            trigger, early, needs = False, False, []
            for sku in self.by_supplier[supplier.code]:
                if sku.code in catalog.DISCONTINUED and d >= catalog.DISCONTINUED[sku.code]:
                    continue
                if sku.launched and d < sku.launched - timedelta(days=lead + 30):
                    continue
                error = max(0.6, 1 + self.rng.gauss(0, 0.12))
                position = self._position(sku)
                if position < self.forecast(sku, d, lead + 21) * error:
                    trigger = True
                elif position < self.forecast(sku, d, lead + 60) * error:
                    early = True
                need = self.forecast(sku, d, lead + 110) * error - position
                if need > supplier.moq * 0.25:
                    needs.append((sku, need))
            if needs:
                wanted[supplier.code] = (supplier, needs, early)
            if trigger and needs:
                triggered.add(supplier.port_locode)
                self._place_po(now + timedelta(minutes=self.rng.randint(20, 300)), supplier, needs)
                del wanted[supplier.code]
        for supplier, needs, early in wanted.values():
            if early and supplier.port_locode in triggered:
                self._place_po(now + timedelta(minutes=self.rng.randint(20, 300)), supplier, needs)

    def _place_po(self, when: datetime, supplier: Supplier, needs) -> None:
        self._po_seq[when.year] += 1
        po = Po(f"PO-{when.year}-{self._po_seq[when.year]:04d}", supplier, when)
        value = sum(need * float(sku.family.cost_usd) for sku, need in needs)
        if value < MIN_ORDER_USD:  # the factory's minimum order value: top every line up
            needs = [(sku, need * MIN_ORDER_USD / value) for sku, need in needs]
        for n, (sku, need) in enumerate(sorted(needs, key=lambda x: x[0].code), 1):
            units = sku.family.carton.units
            quantity = max(supplier.moq, -(-int(need) // units) * units)
            quantity = -(-quantity // units) * units
            po.lines.append(PoLine(po, n, sku, quantity))
            self.on_order[sku.code] += quantity
        self.pos.append(po)
        self._last_po[supplier.code] = when.date()
        self._event(when, "po.placed", po)
        self._event(when + timedelta(minutes=40), "po.status", po, status="sent")
        first = supplier.sales.split()[0]
        sent = when + timedelta(minutes=40)
        self._say(sent, supplier, "us", self.rng.choice([
            f"Hi {first}, new PO {po.number} attached. Pls confirm price and ETD, thanks!",
            f"Hi {first}! PO {po.number} for {len(po.lines)} items, pls check and send PI 🙏",
            f"{first}, here's {po.number}. Same packaging as last time. Can you confirm delivery?"]))
        self._say(sent + timedelta(seconds=20), supplier, "us", f"[文件] {po.number}.pdf")
        confirm_day = self._china_working_day(when.astimezone(CHINA).date(), self.rng.randint(2, 4))
        self._schedule(at(confirm_day, self.rng.randint(15, 19), CHINA, self.rng.randint(0, 59)), self._confirm, po)

    def _china_working_day(self, d: date, n: int) -> date:
        while n > 0:
            d += timedelta(days=1)
            if factory_capacity(d) > 0:
                n -= 1
        return d

    def _confirm(self, when: datetime, po: Po) -> None:
        rng, supplier = self.rng, po.supplier
        d = when.date()
        self._pi_seq[supplier.code] += 1
        po.pi_number = PI_FORMATS[supplier.code].format(d=d, n=self._pi_seq[supplier.code])
        po.pi_date = d
        for line in po.lines:
            line.unit_price = catalog.unit_price(line.sku, d)
        days = max(k.family.production_days for k in (ln.sku for ln in po.lines))
        start = d + timedelta(days=6 if supplier.deposit else 2)
        # Factories quote optimistically, and in January they quote as if New Year were not coming.
        optimistic = add_factory_days(start, days)
        if d < date(2026, 2, 1) and optimistic > date(2026, 2, 9):
            closure = sum(1 for i in range((optimistic - start).days) if factory_capacity(start + timedelta(days=i)) == 0
                          and (start + timedelta(days=i)).weekday() != 6)
            optimistic -= timedelta(days=closure // 2)
        po.etd = po.quoted_etd = optimistic + timedelta(days=7)
        po.status = "confirmed"
        filename = f"{po.pi_number}.pdf"
        self.documents.append(Document("proforma_invoice", filename, d, po))
        self._event(when, "po.confirmed", po, pi_number=po.pi_number, etd=po.etd)
        self._state("pdf", filename, when, po.number, "pi_number", po.pi_number)
        self._state("pdf", filename, when, po.number, "etd", po.etd.isoformat())
        for line in po.lines:
            self._state("pdf", filename, when, po.number, f"unit_price:{line.sku.factory_code}", str(line.unit_price))
        self._say(when, supplier, "them", self.rng.choice(["Hi, PI attached", "PI pls check", "您好，PI请查收"]))
        self._say(when + timedelta(seconds=15), supplier, "them", f"[文件] {filename}")
        etd_cn = f"交期{po.etd.month}月{po.etd.day}号左右"
        message = self._say(when + timedelta(minutes=1), supplier, "them",
                            rng.choice([f"{etd_cn}，ETD around {po.etd.month}/{po.etd.day}",
                                        f"ETD {po.etd.month}/{po.etd.day}", etd_cn]))
        self._state("wechat", message, when, po.number, "etd", po.etd.isoformat())

        if supplier.deposit:
            bill = self._bill(d, supplier.qb_name, po.pi_number, self._memo(po, f"{int(supplier.deposit * 100)}% deposit"),
                              [("Inventory Asset:Supplier Deposits", money(po.total * supplier.deposit))],
                              supplier.currency, due_days=3)
            pay_day = add_us_business_days(when.astimezone(US_EAST).date(), rng.randint(1, 3))
            self._schedule(at(pay_day, rng.randint(10, 16), US_EAST), self._pay_deposit, po, bill)
        else:
            self._schedule(at(start, 8, CHINA), self._start_production, po)

    def _pay_deposit(self, when: datetime, po: Po, bill: Bill) -> None:
        po.deposit_paid = when.date()
        self._pay(bill, when.date())
        amount = f"{po.currency} {bill.amount:,.2f}"
        self._say(when, po.supplier, "us", self.rng.choice([f"Deposit paid today, {amount}. Pls check 🙏",
                                                            f"Hi, we sent the deposit for {po.number} ({amount})"]))
        self._say(when + timedelta(seconds=30), po.supplier, "us", "[图片]")
        ack = self._china_working_day(when.astimezone(CHINA).date(), self.rng.randint(1, 2))
        self._schedule(at(ack, 10, CHINA, self.rng.randint(0, 59)), self._start_production, po)

    def _start_production(self, when: datetime, po: Po) -> None:
        rng = self.rng
        if po.supplier.deposit:
            self._say(when, po.supplier, "them", rng.choice(["收到，谢谢", "Received, thank you", "定金收到了，马上安排生产"]))
        po.status = "in_production"
        self._event(when, "po.status", po, status="in_production")
        days = max(k.family.production_days for k in (ln.sku for ln in po.lines))
        ready = add_factory_days(when.date(), days * rng.uniform(0.88, 1.18) + rng.randint(0, 2))
        if ready + timedelta(days=7) > po.etd + timedelta(days=3):
            notice = max(when.date() + timedelta(days=7), po.etd - timedelta(days=12))
            self._schedule(at(notice, rng.randint(9, 18), CHINA, rng.randint(0, 59)), self._slip, po,
                           ready + timedelta(days=7))
        if rng.random() < 0.5:
            mid = when + timedelta(days=rng.randint(7, 20))
            self._schedule(mid, self._chat_photo, po)
        inspection = ready - timedelta(days=1)
        self._schedule(at(inspection, 10, CHINA), self._inspect, po, 1)

    def _slip(self, when: datetime, po: Po, new_etd: date) -> None:
        if po.status not in ("in_production", "confirmed") or new_etd <= po.etd:
            return
        reason_en, reason_cn = self.rng.choice(SLIP_REASONS)
        po.etd = new_etd
        self._event(when, "po.etd", po, etd=new_etd)
        text = self.rng.choice([
            f"不好意思，{reason_cn}，{po.number}交期要推迟到{new_etd.month}月{new_etd.day}号",
            f"Sorry, {reason_en}. ETD for {po.number} will be {new_etd.month}/{new_etd.day}",
            f"Hi, {po.pi_number} 大货要晚一点，{reason_cn}，预计{new_etd.month}/{new_etd.day}出货"])
        message = self._say(when, po.supplier, "them", text)
        self._state("wechat", message, when, po.number, "etd", new_etd.isoformat())
        self._say(when + timedelta(hours=self.rng.randint(1, 9)), po.supplier, "us",
                  self.rng.choice(["Ok noted. Pls try to keep this date", "Again?? 😩 ok pls don't slip further",
                                   "Understood, thanks for letting me know"]))

    def _chat_photo(self, when: datetime, po: Po) -> None:
        self._say(when, po.supplier, "them", self.rng.choice(["大货生产中", "production photos", "包装样品"]))
        for i in range(self.rng.randint(1, 3)):
            self._say(when + timedelta(seconds=10 * (i + 1)), po.supplier, "them", "[图片]")

    def _inspect(self, when: datetime, po: Po, attempt: int) -> None:
        rng, d = self.rng, when.date()
        lot = sum(line.quantity for line in po.lines)
        sample = 50 if lot <= 500 else 80 if lot <= 1200 else 125 if lot <= 3200 else 200 if lot <= 10000 else 315
        fail_rate = max(QC_FAIL.get(ln.sku.family.code, 0.05) for ln in po.lines) if attempt == 1 else 0.03
        result = "FAIL" if rng.random() < fail_rate else "PASS"
        family = rng.choice([ln.sku.family.code for ln in po.lines])
        pool = DEFECTS.get(family, []) + GENERIC_DEFECTS
        defects = [(text, rng.choice(["major", "minor"]), rng.randint(1, 4)) for text in rng.sample(pool, rng.randint(1, 3))]
        if result == "FAIL":
            defects[0] = (defects[0][0], "major", rng.randint(6, 14))
        self._n["qc"] += 1
        qc = QcInspection(f"LCI-{d:%y%m%d}-{self._n['qc']:03d}", po, d, "Linkcheck Inspection Services", result,
                          sample, defects)
        po.inspections.append(qc)
        filename = f"{qc.report_no}.pdf"
        self.documents.append(Document("qc_report", filename, d, qc))
        self._event(when + timedelta(hours=6), "qc.inspected", qc)
        self._state("pdf", filename, when, po.number, "qc_result", result)
        later = when + timedelta(hours=rng.randint(5, 9))
        if result == "FAIL":
            self._say(later, po.supplier, "us", f"QC failed on {po.number}, report attached. Main issue: {defects[0][0]}")
            self._say(later + timedelta(seconds=20), po.supplier, "us", f"[文件] {filename}")
            rework = rng.randint(5, 10)
            reply = self._say(later + timedelta(hours=rng.randint(1, 4)), po.supplier, "them",
                              f"好的，我们返工，需要{rework}天左右 / ok we rework, about {rework} days")
            ready = add_factory_days(d, rework)
            new_etd = ready + timedelta(days=7)
            if new_etd > po.etd:
                po.etd = new_etd
                self._event(later, "po.etd", po, etd=new_etd)
                self._state("wechat", reply, later, po.number, "etd", new_etd.isoformat())
            self._schedule(at(ready - timedelta(days=1), 10, CHINA), self._inspect, po, attempt + 1)
            return
        self._say(later, po.supplier, "us", rng.choice([f"QC passed for {po.number} 👍", "Inspection passed, thanks!"]))
        po.ready = d + timedelta(days=1)
        po.status = "ready"
        self._event(later, "po.status", po, status="ready")
        if "against B/L" in po.supplier.payment_terms:
            self._book(later, po, po.ready + timedelta(days=3))
        else:
            share = 1 - po.supplier.deposit
            bill = self._bill(d, po.supplier.qb_name, f"{po.pi_number}-B",
                              self._memo(po, "balance" if po.supplier.deposit else "full payment"),
                              [("Inventory Asset:Supplier Deposits", money(po.total * share))], po.currency, due_days=2)
            self._say(later + timedelta(hours=1), po.supplier, "them",
                      f"Goods ready. Pls arrange balance payment {po.currency} {bill.amount:,.2f} before loading, thanks")
            pay_day = add_us_business_days(later.astimezone(US_EAST).date(), rng.randint(1, 3))
            self._schedule(at(pay_day, rng.randint(10, 16), US_EAST), self._pay_balance, po, bill)

    def _pay_balance(self, when: datetime, po: Po, bill: Bill) -> None:
        po.balance_paid = when.date()
        self._pay(bill, when.date())
        self._say(when, po.supplier, "us", f"Balance paid for {po.number}, pls arrange shipment")
        self._book(when, po, max(po.ready + timedelta(days=3), when.date() + timedelta(days=3)))

    def _book(self, when: datetime, po: Po, earliest: date) -> None:
        port = po.supplier.port_locode
        today = when.astimezone(CHINA).date()
        # Join cargo already booked from this port within ten days, if its cut-off has not passed.
        for key in sorted(self._groups, key=lambda k: k[2]):
            p, route, sailing = key
            if p == port and earliest <= sailing <= earliest + timedelta(days=10) and sailing - timedelta(days=5) > today:
                po.route = route
                self._groups[key].append(po)
                return
        # Small cargo waits at the forwarder's warehouse for another PO from the same port that is nearly ready.
        if po.cbm < 14:
            partners = [p.etd for p in self.pos if p is not po and p.supplier.port_locode == port and p.etd
                        and p.status in ("confirmed", "in_production", "ready") and 0 <= (p.etd - earliest).days <= 10]
            if partners:
                earliest = max(earliest, min(partners))
        urgent = any(self.stock["3PL-NJ"][ln.sku.code] < self.forecast(ln.sku, earliest, 21) for ln in po.lines)
        route = "USLAX" if urgent and self.rng.random() < 0.7 else "USNYC"
        po.route = route
        sailing = next_sailing(port, route, max(earliest, today + timedelta(days=6)))
        key = (port, route, sailing)
        if key not in self._groups:
            self._groups[key] = []
            self._schedule(at(sailing - timedelta(days=5), 17, CHINA), self._close_sailing, key)
        self._groups[key].append(po)

    def _close_sailing(self, when: datetime, key) -> None:
        port, route, sailing = key
        pos = self._groups.pop(key)
        pieces = [[ln, ln.quantity, ln.cartons] for po in pos for ln in po.lines]
        total = sum(c * ln.sku.family.carton.cbm for ln, _, c in pieces)
        containers = []
        if total < 14:
            for po in pos:
                containers.append(("LCL", [p for p in pieces if p[0].po is po]))
        else:
            remaining = list(pieces)
            while remaining:
                left = sum(c * ln.sku.family.carton.cbm for ln, _, c in remaining)
                mode, cap = ("40HQ", Decimal(60)) if left > 25 else ("20GP", Decimal(25)) if left > 12 else ("LCL", left)
                load, used = [], Decimal(0)
                while remaining:
                    ln, qty, cartons = remaining[0]
                    cbm = ln.sku.family.carton.cbm
                    fit = min(cartons, int((cap - used) / cbm)) if cbm else cartons
                    if fit <= 0:
                        break
                    units = min(qty, fit * ln.sku.family.carton.units)
                    load.append([ln, units, fit])
                    used += fit * cbm
                    if fit < cartons:
                        remaining[0] = [ln, qty - units, cartons - fit]
                        break
                    remaining.pop(0)
                containers.append((mode, load))
        for mode, load in containers:
            self._create_shipment(when, port, route, sailing, mode, load)

    def _create_shipment(self, when, port, route, sailing, mode, load) -> None:
        rng = self.rng
        self._n["booking"] += 1
        n = self._n["booking"]
        weekday, transit = SAILINGS[(port, route)]
        etd = at(sailing, rng.randint(18, 23), CHINA)
        dest_tz = US_EAST if route == "USNYC" else US_WEST
        eta = at((etd + timedelta(days=transit + rng.randint(-1, 2))).date(), rng.randint(5, 10), dest_tz)
        peak = date(2026, 7, 15) <= sailing <= date(2026, 10, 31) or date(2025, 7, 15) <= sailing <= date(2025, 10, 31)
        cbm = sum(c * ln.sku.family.carton.cbm for ln, _, c in load)
        if mode == "LCL":
            freight = money(Decimal(rng.randint(85, 110)) * cbm + 180)
        else:
            base = rng.randint(3700, 4900) if route == "USNYC" else rng.randint(2500, 3300)
            base += (900 if route == "USNYC" else 600) if peak else 0
            freight = money(base * (Decimal("0.78") if mode == "20GP" else 1))
        owner = rng.choice(["MSK", "CMA", "TGH", "OOL", "TCL", "SEG"])
        shipment = Shipment(
            booking_no=f"PBL{port[2:]}{sailing:%y%m}{n:03d}", hbl=f"PBLHB{sailing:%y}{n:05d}", mode=mode,
            container_no=None if mode == "LCL" else ids.iso6346(owner, rng.randint(100000, 999999)),
            seal_no=None if mode == "LCL" else f"{owner[:2]}{rng.randint(1_000_000, 9_999_999)}",
            origin=port, destination=route, vessel=rng.choice(VESSELS), voyage=f"{rng.randint(10, 99):03d}E",
            etd=etd, eta=eta, freight=freight,
            lines=[ShipmentLine(ln, qty, cartons) for ln, qty, cartons in load])
        self.shipments.append(shipment)
        for po in shipment.pos:
            po.shipments.append(shipment)
        self._event(when, "shipment.booked", shipment)
        msg = self._email(when, FORWARDER, f"Booking Confirmation - SO {shipment.booking_no} - {PORTS[port]} to "
                          f"{PORTS[route]} - {shipment.vessel} {shipment.voyage}",
                          self._booking_body(shipment), attachments=(f"SO_{shipment.booking_no}.pdf",))
        for field_, value in (("etd", etd.date().isoformat()), ("eta", eta.date().isoformat())):
            self._state("email", msg, when, shipment.booking_no, field_, value)
        if rng.random() < 0.1:
            self._schedule(etd - timedelta(days=2), self._roll, shipment)
        if shipment.container_no:
            supplier = shipment.pos[0].supplier
            loaded = etd - timedelta(days=rng.randint(2, 4))
            text = rng.choice([f"已装柜 container loaded: {shipment.container_no} seal {shipment.seal_no}",
                               f"Container {shipment.container_no} loaded today 👍"])
            message = self._say(loaded, supplier, "them", text)
            self._state("wechat", message, loaded, shipment.booking_no, "container_no", shipment.container_no)
            self._say(loaded + timedelta(seconds=40), supplier, "them", "[图片]")
        self._schedule(etd, self._depart, shipment)

    def _roll(self, when: datetime, shipment: Shipment) -> None:
        shipment.etd += timedelta(days=7)
        shipment.eta += timedelta(days=7)
        self._event(when, "shipment.etd", shipment, etd=shipment.etd, eta=shipment.eta)
        msg = self._email(when, FORWARDER, f"RE: Booking Confirmation - SO {shipment.booking_no} - ROLLED",
                          f"Dear Maya,\n\nCarrier has rolled SO {shipment.booking_no} due to vessel overbooking. "
                          f"New ETD {shipment.etd:%d %b %Y}, ETA {shipment.eta:%d %b %Y}. Sorry for the inconvenience."
                          f"\n\n{self._signature(FORWARDER)}")
        self._state("email", msg, when, shipment.booking_no, "etd", shipment.etd.date().isoformat())
        for event in list(self._heap):
            if event[2] == self._depart and event[3][0] is shipment:
                self._heap.remove(event)
        heapq.heapify(self._heap)
        self._schedule(shipment.etd, self._depart, shipment)

    def _depart(self, when: datetime, shipment: Shipment) -> None:
        rng = self.rng
        shipment.status = "departed"
        for line in shipment.lines:
            line.po_line.shipped += line.quantity
        self._event(when, "shipment.departed", shipment)
        msg = self._email(when + timedelta(hours=14), FORWARDER,
                          f"Shipping Advice / Pre-alert - HBL {shipment.hbl} - {shipment.container_no or 'LCL'}",
                          self._advice_body(shipment), attachments=(f"HBL_{shipment.hbl}.pdf",))
        self._state("email", msg, when, shipment.booking_no, "eta", shipment.eta.date().isoformat())
        for po in shipment.pos:
            pending = [s for s in po.shipments if s.status == "booked"]
            if not pending:
                po.status = "shipped"
                if po.etd != when.date():
                    po.etd = when.date()
                    self._event(when, "po.etd", po, etd=po.etd)
                self._event(when, "po.status", po, status="shipped")
                for line in po.lines:
                    self.on_order[line.sku.code] -= line.quantity - line.shipped
            filename = f"CI-PL_{po.pi_number}_{shipment.container_no or shipment.hbl}.pdf"
            self.documents.append(Document("commercial_invoice", filename, when.date(), (shipment, po)))
            for sl in shipment.lines:
                if sl.po_line.po is po:
                    self._state("pdf", filename, when, po.number, f"shipped:{sl.po_line.sku.factory_code}",
                                str(sl.quantity))
            self._say(when + timedelta(hours=20), po.supplier, "them", f"[文件] {filename}")
            if "against B/L" in po.supplier.payment_terms and not pending:
                bill = self._bill(when.date(), po.supplier.qb_name, f"{po.pi_number}-B", self._memo(po, "balance"),
                                  [("Inventory Asset:Supplier Deposits", money(po.total * (1 - po.supplier.deposit)))],
                                  po.currency, due_days=5)
                self._say(when + timedelta(days=1), po.supplier, "them",
                          f"B/L copy attached, pls arrange balance {po.currency} {bill.amount:,.2f}")
                pay_day = add_us_business_days(when.astimezone(US_EAST).date(), rng.randint(2, 5))
                self._schedule(at(pay_day, 11, US_EAST), self._pay_late_balance, bill, po)
        if rng.random() < 0.18:
            self._schedule(shipment.eta - timedelta(days=6), self._delay, shipment)
        self._schedule(at((shipment.eta - timedelta(days=3)).date(), 14, US_EAST), self._file_entry, shipment)
        self._schedule(shipment.eta, self._arrive, shipment)

    def _pay_late_balance(self, when: datetime, bill: Bill, po: Po) -> None:
        po.balance_paid = when.date()
        self._pay(bill, when.date())
        self._say(when, po.supplier, "us", f"Balance for {po.number} sent today")

    def _delay(self, when: datetime, shipment: Shipment) -> None:
        days = self.rng.randint(2, 9)
        reason = self.rng.choice(["port congestion at destination", "weather delay in transit",
                                  "vessel omitted a port call", "terminal labour slowdown"])
        shipment.eta += timedelta(days=days)
        self._event(when, "shipment.eta", shipment, eta=shipment.eta)
        msg = self._email(when, FORWARDER, f"ETA update - HBL {shipment.hbl} - {shipment.container_no or 'LCL'}",
                          f"Hi Maya,\n\nPlease note revised ETA {shipment.eta:%d %b %Y} for HBL {shipment.hbl} "
                          f"({reason}).\n\n{self._signature(FORWARDER)}")
        self._state("email", msg, when, shipment.booking_no, "eta", shipment.eta.date().isoformat())
        for event in list(self._heap):
            if event[2] in (self._arrive, self._file_entry) and event[3][0] is shipment:
                self._heap.remove(event)
        heapq.heapify(self._heap)
        self._schedule(at((shipment.eta - timedelta(days=3)).date(), 14, US_EAST), self._file_entry, shipment)
        self._schedule(shipment.eta, self._arrive, shipment)

    def _file_entry(self, when: datetime, shipment: Shipment) -> None:
        if shipment.entry:
            return
        self._n["entry"] += 1
        lines = []
        for sl in shipment.lines:
            po = sl.po_line.po
            rate = cny_per_usd(po.pi_date) if po.currency == "CNY" else Decimal(1)
            value = money(sl.quantity * sl.po_line.unit_price / rate)
            family = sl.po_line.sku.family
            lines.append(EntryLine(sl.po_line, sl.quantity, value, money(value * family.duty_general),
                                   money(value * family.duty_301), money(value * catalog.ADDITIONAL_CHINA_DUTY)))
        total_value = sum((ln.value_usd for ln in lines), Decimal(0))
        mpf = min(max(money(total_value * catalog.MPF_RATE), catalog.MPF_MIN), catalog.MPF_MAX)
        entry = CustomsEntry(ids.cbp_entry(BROKER[2], 2_604_000 + self._n["entry"] * 13), shipment, when.date(), lines,
                             mpf, money(total_value * catalog.HMF_RATE), Decimal(125 + 35 + 25 * max(0, len(lines) - 5)))
        shipment.entry = entry
        self.entries.append(entry)
        self._event(when, "customs.entered", entry)
        msg = self._email(when, BROKER, f"Entry Summary {entry.entry_no} - {shipment.container_no or shipment.hbl}",
                          self._entry_body(entry), attachments=(f"7501_{entry.entry_no}.pdf",))
        self._state("email", msg, when, entry.entry_no, "duty_total", str(entry.total))
        self._bill(when.date(), BROKER[0], f"HB-{entry.entry_no[4:11]}", f"Entry {entry.entry_no} "
                   f"{shipment.container_no or shipment.hbl}",
                   [("Inventory Asset:Duty & Customs", entry.total), ("Freight & Brokerage", entry.brokerage)],
                   "USD", due_days=10, pay=True)

    def _arrive(self, when: datetime, shipment: Shipment) -> None:
        shipment.status = "arrived"
        self._event(when, "shipment.arrived", shipment)
        lfd = (when + timedelta(days=4)).date()
        self._email(when - timedelta(hours=30), FORWARDER, f"Arrival Notice - HBL {shipment.hbl} - "
                    f"{shipment.container_no or 'LCL'}",
                    f"Dear Maya,\n\nShipment HBL {shipment.hbl} ({shipment.container_no or 'LCL'}) on {shipment.vessel} "
                    f"{shipment.voyage} is arriving {PORTS[shipment.destination]} on {shipment.eta:%d %b %Y}.\n"
                    f"Last free day at terminal: {lfd:%d %b %Y}.\nCustoms status: entry filed by "
                    f"{BROKER[0]}.\n\n{self._signature(FORWARDER)}", attachments=(f"AN_{shipment.hbl}.pdf",))
        days = self.rng.randint(3, 6) if shipment.destination == "USNYC" else self.rng.randint(11, 15)
        delivery = add_us_business_days(when.astimezone(US_EAST).date(), max(1, days * 5 // 7))
        self._schedule(at(delivery, self.rng.randint(8, 14), US_EAST), self._deliver, shipment)

    def _deliver(self, when: datetime, shipment: Shipment) -> None:
        rng = self.rng
        shipment.status = "delivered"
        shipment.delivered = when
        per_sku: dict[Sku, int] = defaultdict(int)
        for sl in shipment.lines:
            per_sku[sl.po_line.sku] += sl.quantity
        lines = []
        for sku, expected in per_sku.items():
            short = sku.family.carton.units if rng.random() < 0.03 else 0
            received = max(0, expected - short)
            damaged = min(received, poisson(rng, received * sku.family.damage_rate))
            lines.append(ReceiptLine(sku, expected, received, damaged))
            self.stock["3PL-NJ"][sku.code] += received - damaged
            self.on_order[sku.code] -= expected
        self._n["receipt"] += 1
        receipt = Receipt(f"GSF-RCV-{self._n['receipt']:06d}", f"ASN{when:%y%m%d}{self._n['receipt'] % 1000:03d}",
                          shipment, when, lines)
        shipment.receipt = receipt
        self.receipts.append(receipt)
        self._event(when, "shipment.delivered", shipment)
        problems = [ln for ln in lines if ln.damaged or ln.received < ln.expected]
        body = (f"Hi Maya,\n\nReceiving complete for {shipment.container_no or shipment.hbl} under {receipt.receipt_no}"
                f" (ASN {receipt.asn_no}).\n")
        if problems:
            body += "Discrepancies:\n" + "".join(
                f"  {ln.sku.tpl_item_code} ({ln.sku.tpl_client_sku or 'no client SKU'}): expected {ln.expected}, "
                f"received {ln.received}, damaged {ln.damaged}\n" for ln in problems)
        else:
            body += "No discrepancies.\n"
        msg = self._email(when + timedelta(hours=5), TPL, f"Receipt complete {receipt.receipt_no} - "
                          f"{shipment.container_no or shipment.hbl}", body + f"\n{self._signature(TPL)}")
        for ln in problems:
            self._state("email", msg, when, receipt.receipt_no, f"damaged:{ln.sku.tpl_item_code}", str(ln.damaged))
        self._month[when.strftime("%Y-%m")]["receiving_fcl" if shipment.container_no else "receiving_lcl"] += 1
        destination = Decimal(685 + 95) if shipment.destination == "USNYC" else Decimal(1950)
        self._bill(when.date(), FORWARDER[0], f"PBL-INV-{when:%y}{self._n['receipt']:05d}",
                   f"{shipment.hbl} / {shipment.container_no or 'LCL'} / " + " ".join(self._short_po(p) for p in shipment.pos),
                   [("Freight In", shipment.freight), ("Freight In", destination)], "USD", due_days=15, pay=True)
        for po in shipment.pos:
            if po.status == "shipped" and all(s.status == "delivered" for s in po.shipments):
                po.status = "received"
                self._event(when, "po.status", po, status="received")

    # --- Amazon and the 3PL -------------------------------------------------------------

    def _replenish_fba(self, now: datetime) -> None:
        rng, d = self.rng, now.date()
        lines = []
        for sku in self._active(d, "amazon"):
            rate = self.expected_units(sku, d, "amazon")
            position = self.stock["FBA-US"][sku.code] + self.fba_inbound[sku.code]
            if position >= rate * 35:
                continue
            reserve = self.forecast(sku, d, 14, ("shopify",))
            available = self.stock["3PL-NJ"][sku.code] - reserve
            units = sku.family.carton.units
            qty = int(min(rate * 60 - position, available) // units) * units
            if qty > 0:
                lines.append([sku, qty, 0])
        if not lines:
            return
        centres = rng.sample(FULFILMENT_CENTRES, 1 if len(lines) < 6 else 2)
        for i, centre in enumerate(centres):
            mine = lines[i::len(centres)]
            self._n["fba"] += 1
            shipment = FbaShipment(ids.fba_shipment_id(rng), f"FBA ({now:%m/%d/%Y %H:%M}) - {self._n['fba']}", now,
                                   centre, mine)
            self.fba_shipments.append(shipment)
            self._event(now, "fba.created", shipment)
            self._schedule(at(add_us_business_days(d, 1), 15, US_EAST), self._ship_fba, shipment)

    def _ship_fba(self, when: datetime, shipment: FbaShipment) -> None:
        shipment.shipped = when
        for line in shipment.lines:
            sku, qty = line[0], line[1]
            qty = min(qty, max(0, self.stock["3PL-NJ"][sku.code]))
            line[1] = qty
            self.stock["3PL-NJ"][sku.code] -= qty
            self.fba_inbound[sku.code] += qty
        self.outbound.append((when, shipment.shipment_id, [(ln[0], ln[1]) for ln in shipment.lines], "LTL"))
        month = when.strftime("%Y-%m")
        self._month[month]["fba_units"] += sum(ln[1] for ln in shipment.lines)
        self._month[month]["fba_shipments"] += 1
        d = when.date()
        backlog = (self.rng.randint(7, 14) if d.month in (10, 11, 12)
                   else self.rng.randint(6, 12) if date(d.year, 6, 15) <= d <= date(d.year, 7, 6)
                   else self.rng.randint(2, 7))
        self._schedule(when + timedelta(days=self.rng.randint(1, 3) + backlog), self._receive_fba, shipment)

    def _receive_fba(self, when: datetime, shipment: FbaShipment) -> None:
        shipment.received = when
        for line in shipment.lines:
            sku, qty = line[0], line[1]
            lost = self.rng.randint(1, 3) if self.rng.random() < 0.06 and qty > 3 else 0
            line[2] = qty - lost
            self.fba_inbound[sku.code] -= qty
            self.stock["FBA-US"][sku.code] += qty - lost

    def _tpl_invoice(self, when: datetime) -> None:
        month = (when.date().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        m = self._month[month]
        units_on_hand = sum(max(0, v) for v in self.stock["3PL-NJ"].values())
        pallets = max(1, units_on_hand // 900)
        lines = [("Warehousing & Fulfilment", money(pallets * Decimal("18.00") * 4)),
                 ("Warehousing & Fulfilment", money(m["orders"] * Decimal("3.10")
                                                    + max(0, m["units"] - m["orders"]) * Decimal("0.85"))),
                 ("Warehousing & Fulfilment", money(m["receiving_fcl"] * 450 + m["receiving_lcl"] * 160)),
                 ("Warehousing & Fulfilment", money(m["fba_units"] * Decimal("0.40") + m["fba_shipments"] * 45))]
        lines = [(account, amount) for account, amount in lines if amount]
        self._bill(when.date(), "Garden State Fulfillment LLC", f"GSF-{month.replace('-', '')}",
                   f"{month} storage, fulfilment, receiving, FBA prep", lines, "USD", due_days=15, pay=True)

    # --- messages, documents, money -----------------------------------------------------

    def _say(self, when: datetime, supplier: Supplier, who: str, text: str) -> str:
        sender = "Maya @ Acme Hearth" if who == "us" else supplier.sales_wechat
        self.messages.append(Message(when, supplier.code, sender, text))
        return f"wechat:{supplier.code}:{len(self.messages)}"

    def _small_talk(self, when: datetime, supplier: Supplier) -> None:
        rng = self.rng
        kind = rng.random()
        if kind < 0.35:
            self._say(when, supplier, "them", f"[语音] 0:{rng.randint(4, 48):02d}")
            self._say(when + timedelta(minutes=rng.randint(1, 30)), supplier, "us", "Sorry can you type it? 🙏")
        elif kind < 0.6:
            self._say(when, supplier, "us", rng.choice(["Hi, can you quote 3000pcs in a new colour?",
                                                        "Do you have a catalogue for next year?",
                                                        "Can you send 2 samples by DHL?"]))
            self._say(when + timedelta(hours=rng.randint(1, 20)), supplier, "them",
                      rng.choice(["好的，明天报给您", "OK I will check with boss", "Sure, will send this week"]))
        elif kind < 0.8:
            self._say(when, supplier, "them", rng.choice(["👍", "OK", "好的", "收到", "[动画表情]"]))
        else:
            awb = rng.randint(10**9, 10**10 - 1)
            message = self._say(when, supplier, "them", f"Samples sent by DHL, AWB {awb}")
            self._state("wechat", message, when, supplier.code, "sample_awb", str(awb))

    def _holiday_notices(self, when: datetime, which: str) -> None:
        for i, supplier in enumerate(self.suppliers):
            t = when + timedelta(minutes=37 * i)
            if which == "cny":
                text = ("春节放假通知：我司2月9日至3月1日放假，3月2日正式上班。节前最后出货2月6日。"
                        "CNY holiday Feb 9 - Mar 1, back to work Mar 2. Last shipment before holiday Feb 6.")
                message = self._say(t, supplier, "them", text)
                self._state("wechat", message, t, supplier.code, "closed", "2026-02-09/2026-03-01")
            else:
                message = self._say(t, supplier, "them", "国庆放假通知：10月1日至10月7日放假，10月8日上班。祝国庆快乐！")
                self._state("wechat", message, t, supplier.code, "closed", "2026-10-01/2026-10-07")

    def _price_notice(self, when: datetime, supplier: Supplier, change) -> None:
        message = self._say(when, supplier, "them", f"{change.reason_cn} / {change.reason_en}: "
                            f"{change.percent:+}% from {change.effective:%b %d}")
        self._state("wechat", message, when, supplier.code, "price_change",
                    f"{change.percent}%@{change.effective.isoformat()}")

    def _seed_customers(self) -> None:
        """People who bought in 2025 and may come back."""
        prior = int(0.7 * BASE_ORDERS_PER_DAY["shopify"] * self.scale * 1.1 * (YEAR_START - SIM_START).days)
        span = (YEAR_START - SIM_START).days * 86400
        for i in range(prior):
            person = people.person(self.rng, self._n["person"], self._emails)
            self._n["person"] += 1
            self._customer_id += self.rng.randint(2_000_000, 40_000_000)
            created = at(SIM_START, 0, US_EAST) + timedelta(seconds=span * (i + self.rng.random()) / prior)
            self.customers.append(Customer(self._customer_id, person, created))

    def _memo(self, po: Po, what: str) -> str:
        return self.rng.choice([f"{what} {po.number}", f"{what} - {self._short_po(po)}", f"{po.pi_number} {what}",
                                f"{what} PI {po.pi_number} / {po.number}"])

    def _short_po(self, po: Po) -> str:
        n = int(po.number.split("-")[2])
        return self.rng.choice([po.number, f"PO{n}", f"po {n:04d}", f"PO#{po.number[3:]}"])

    def _bill(self, on: date, vendor: str, doc: str, memo: str, lines, currency: str, *, due_days: int,
              pay: bool = False) -> Bill:
        self._n["qbo"] += 1
        rate = (Decimal(1) / cny_per_usd(on)).quantize(Decimal("0.000001")) if currency == "CNY" else Decimal(1)
        bill = Bill(100 + self._n["qbo"], vendor, on, on + timedelta(days=due_days), doc, memo, lines, currency, rate)
        self.bills.append(bill)
        if pay:
            paid = add_us_business_days(bill.due, self.rng.randint(-2, 3))
            if paid <= TODAY:
                self._pay(bill, paid)
        return bill

    def _pay(self, bill: Bill, on: date) -> None:
        self._n["qbo"] += 1
        bill.paid, bill.payment_id = on, 100 + self._n["qbo"]

    def _email(self, when: datetime, sender, subject: str, body: str, attachments=()) -> str:
        self._n["email"] += 1
        message_id = f"<{when:%Y%m%d%H%M%S}.{self._n['email']}@{sender[1]}>"
        name = {FORWARDER: "Jenny Wu", BROKER: "Tom Reyes", TPL: "Receiving Team"}[sender]
        address = {FORWARDER: f"ops@{FORWARDER[1]}", BROKER: f"entries@{BROKER[1]}", TPL: f"receiving@{TPL[1]}"}[sender]
        self.emails.append(Email(when, (f"{name} ({sender[0]})", address), catalog.BRAND_OPS, subject, body,
                                 message_id, attachments=tuple(attachments)))
        return message_id

    def _signature(self, sender) -> str:
        return {FORWARDER: f"Best regards,\nJenny Wu\nOcean Export Operations\n{FORWARDER[0]}\nT +1 (562) 555-0148",
                BROKER: f"Regards,\nTom Reyes\nLicensed Customs Broker\n{BROKER[0]}\nT +1 (973) 555-0121",
                TPL: f"Thanks,\nReceiving Team\n{TPL[0]} - {TPL[2]}"}[sender]

    def _booking_body(self, s: Shipment) -> str:
        cutoff = (s.etd - timedelta(days=3)).date()
        shippers = ", ".join(p.supplier.name for p in s.pos)
        return (f"Dear Maya,\n\nPlease find booking confirmation below.\n\nSO: {s.booking_no}\nShipper(s): {shippers}\n"
                f"Equipment: {'1x' + s.mode if s.mode != 'LCL' else f'LCL {s.cbm:.2f} CBM'}\n"
                f"Vessel/Voyage: {s.vessel} {s.voyage}\nPOL: {PORTS[s.origin]} ({s.origin})  POD: {PORTS[s.destination]} "
                f"({s.destination})\nETD: {s.etd:%d %b %Y}\nETA: {s.eta:%d %b %Y}\nCY cut-off: {cutoff:%d %b %Y} 12:00\n"
                f"SI cut-off: {cutoff - timedelta(days=1):%d %b %Y} 17:00\nPOs: "
                + ", ".join(self._short_po(p) for p in s.pos) + f"\n\n{self._signature(FORWARDER)}")

    def _advice_body(self, s: Shipment) -> str:
        lines = "".join(f"  {sl.po_line.po.number}  {sl.po_line.sku.factory_code:<10} {sl.cartons:>4} ctns "
                        f"{sl.quantity:>6} pcs\n" for sl in s.lines)
        return (f"Dear Maya,\n\nPlease be advised the following shipment has departed.\n\nHBL: {s.hbl}\n"
                f"Container/Seal: {s.container_no or 'LCL'} / {s.seal_no or '-'}\nVessel/Voyage: {s.vessel} {s.voyage}\n"
                f"ATD {PORTS[s.origin]}: {s.etd:%d %b %Y}\nETA {PORTS[s.destination]}: {s.eta:%d %b %Y}\n"
                f"Packages: {sum(sl.cartons for sl in s.lines)} CTNS  {s.gross_kg:.1f} KGS  {s.cbm:.2f} CBM\n\n{lines}\n"
                f"{self._signature(FORWARDER)}")

    def _entry_body(self, e: CustomsEntry) -> str:
        return (f"Hi Maya,\n\nEntry {e.entry_no} filed for {e.shipment.container_no or e.shipment.hbl}.\n\n"
                f"Entered value: USD {sum(ln.value_usd for ln in e.lines):,.2f}\n"
                f"Duty (HTS): USD {sum(ln.general for ln in e.lines):,.2f}\n"
                f"Section 301: USD {sum(ln.section_301 for ln in e.lines):,.2f}\n"
                f"Additional duties: USD {sum(ln.additional for ln in e.lines):,.2f}\n"
                f"MPF: USD {e.mpf:,.2f}\nHMF: USD {e.hmf:,.2f}\nTotal duties and fees: USD {e.total:,.2f}\n\n"
                f"Our invoice for brokerage (USD {e.brokerage:,.2f}) follows.\n\n{self._signature(BROKER)}")

    def _state(self, source: str, ref: str, when: datetime, subject: str, field_: str, value: str) -> None:
        self.statements.append(Statement(source, ref, when, subject, field_, value))

    # --- the morning of 1 October -------------------------------------------------------

    def _snapshot(self) -> None:
        counted = NOW - timedelta(hours=self.rng.randint(5, 9))
        factory: dict[tuple, int] = defaultdict(int)
        ocean: dict[Sku, int] = defaultdict(int)
        for po in self.pos:
            if po.status in ("in_production", "ready"):
                for line in po.lines:
                    factory[(line.sku, f"FAC-{po.supplier.code}")] += line.quantity - line.shipped
        for s in self.shipments:
            if s.status in ("departed", "arrived"):
                for sl in s.lines:
                    ocean[sl.po_line.sku] += sl.quantity
        positions = [InventoryPosition(sku, loc, qty, counted) for (sku, loc), qty in factory.items() if qty > 0]
        positions += [InventoryPosition(sku, "OCEAN", qty, counted) for sku, qty in ocean.items() if qty > 0]
        for location, stock in self.stock.items():
            positions += [InventoryPosition(next(k for k in self.skus if k.code == code), location, qty, counted)
                          for code, qty in stock.items() if qty > 0]
        self.inventory = positions
        self._out.append(Event(NOW, "inventory.snapshot", positions))

