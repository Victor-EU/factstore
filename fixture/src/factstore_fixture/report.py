"""A realism report: the numbers an operator of this business would recognise, to check
the simulation against how such a brand actually runs."""

from collections import Counter, defaultdict
from decimal import Decimal
from statistics import mean, median

from .clock import NOW, US_EAST, YEAR_START
from .model import AmazonOrder, Event, ShopifyOrder
from .simulate import Simulation


def realism(seed: int = 7, scale: float = 1.0) -> str:
    sim = Simulation(seed, scale)
    monthly = defaultdict(lambda: Counter())
    revenue = Counter()
    shopify_new, shopify_total, seen = 0, 0, set()
    for item in sim.run():
        if isinstance(item, ShopifyOrder) and item.created.astimezone(US_EAST).date() >= YEAR_START:
            month = item.created.astimezone(US_EAST).strftime("%Y-%m")
            monthly[month]["shopify"] += 1
            revenue["shopify"] += item.subtotal
            shopify_total += 1
            if item.customer.created >= item.created:
                shopify_new += 1
        elif isinstance(item, AmazonOrder) and item.purchased.astimezone(US_EAST).date() >= YEAR_START:
            month = item.purchased.astimezone(US_EAST).strftime("%Y-%m")
            monthly[month]["amazon"] += 1
            revenue["amazon"] += sum(ln.item_price - ln.promotion_discount for ln in item.lines)

    out = ["# Realism report", "", f"seed {seed}, scale {scale}, as of {NOW:%Y-%m-%d %H:%M %Z}", ""]
    out += ["## Sales, year to date", "", "| Month | Shopify orders | Amazon orders |", "|---|---|---|"]
    out += [f"| {m} | {c['shopify']:,} | {c['amazon']:,} |" for m, c in sorted(monthly.items())]
    out += ["", f"- Revenue: Shopify ${revenue['shopify']:,.0f}, Amazon ${revenue['amazon']:,.0f}",
            f"- Shopify orders from new customers: {shopify_new / max(1, shopify_total):.0%}",
            f"- Duplicate customer accounts: {sum(1 for c in sim.customers if c.duplicate_of)}",
            f"- Units of demand lost to stockouts: {sum(sim.lost_sales.values()):,}"]

    pos = [p for p in sim.pos if p.pi_date]
    out += ["", "## Purchasing", "",
            f"- POs: {len(sim.pos)} ({Counter(p.status for p in sim.pos)})",
            f"- Median PO: {median(sum(ln.quantity for ln in p.lines) for p in pos):,.0f} units, "
            f"{median(p.cbm for p in pos):.1f} CBM, {median(len(p.lines) for p in pos)} lines",
            f"- QC inspections: {sum(len(p.inspections) for p in pos)}, failed "
            f"{sum(1 for p in pos for q in p.inspections if q.result == 'FAIL')}",
            f"- POs the supplier delayed after the PI: "
            f"{sum(1 for p in pos if sum(1 for s in sim.statements if s.subject == p.number and s.field == 'etd' and s.source == 'wechat') > 1)}"]
    delivered = [p for p in pos if p.status == "received"]
    if delivered:
        lead = [(max(s.delivered for s in p.shipments).date() - p.placed.date()).days for p in delivered]
        slip = [(p.etd - _first_etd(sim, p)).days for p in delivered]  # actual departure vs first quote
        out += [f"- Lead time, PO placed to 3PL receipt: median {median(lead)} days (range {min(lead)}-{max(lead)})",
                f"- ETD slip from the first quote: median {median(slip)} days, max {max(slip)}"]

    ships = sim.shipments
    out += ["", "## Freight and customs", "",
            f"- Shipments: {len(ships)} ({Counter(s.mode for s in ships)}), to {Counter(s.destination for s in ships)}",
            f"- Median freight per CBM: ${median(s.freight / s.cbm for s in ships if s.cbm):.0f}",
            f"- Rolled bookings: {sum(1 for e in sim.emails if 'ROLLED' in e.subject)}; "
            f"late arrivals announced: {sum(1 for e in sim.emails if e.subject.startswith('ETA update'))}"]
    if sim.entries:
        rate = [e.duty / sum(ln.value_usd for ln in e.lines) for e in sim.entries]
        out.append(f"- Duty as share of entered value: median {median(rate):.1%}")
    out += ["", "## Stock on the morning of 1 October", ""]
    by_loc = Counter()
    for p in sim.inventory:
        by_loc[p.location.split("-")[0] if p.location.startswith("FAC") else p.location] += p.quantity
    out += [f"- {loc}: {qty:,} units" for loc, qty in sorted(by_loc.items())]
    out += [f"- FBA inbound shipments: {len(sim.fba_shipments)}",
            "", "## Messages and documents", "",
            f"- WeChat messages: {len(sim.messages):,}; emails: {len(sim.emails)}; "
            f"PDFs: {Counter(d.kind for d in sim.documents)}",
            f"- QuickBooks bills: {len(sim.bills)}"]
    return "\n".join(out) + "\n"


def _first_etd(sim: Simulation, po) -> "date":
    from datetime import date
    first = next(s for s in sim.statements if s.subject == po.number and s.field == "etd")
    return date.fromisoformat(first.value)
