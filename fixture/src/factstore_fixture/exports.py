"""Source-shaped exports: the files a catalogue or ingestion skill would be handed, in the
shapes the real systems produce them, plus the ground truth to score it against.

    shopify/        GraphQL bulk-operation JSONL: products with variants, orders with line items
    amazon/         Seller Central flat files: All Orders, FBA inventory, inbound shipments
    3pl/            the warehouse's CSVs: inventory snapshot, receipts, outbound
    quickbooks/     QuickBooks Online reports: vendor list, transaction list by vendor
    supplier_docs/  PDFs from factories and the inspection agency
    wechat/         one chat export per supplier
    email/          the ops inbox as an mbox: forwarder, customs broker, 3PL
    truth/          ground truth: the SKU crosswalk, shapes, statements, duplicate customers

Orders cover the year to date. Purchasing history starts in July 2025.
"""

import csv
import json
import os
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.utils import format_datetime

from . import catalog, documents, vocabulary
from .clock import NOW, TODAY, US_EAST, YEAR_START
from .model import AmazonOrder, ShopifyOrder
from .simulate import Simulation

FBA_PRODUCT = "Acme Hearth"


def export(outdir: str, seed: int = 7, scale: float = 1.0) -> dict:
    sim = Simulation(seed, scale)
    for d in ("shopify", "amazon", "3pl", "quickbooks", "supplier_docs", "wechat", "email", "truth"):
        os.makedirs(os.path.join(outdir, d), exist_ok=True)
    rng = random.Random(f"{seed}:exports")
    counts = defaultdict(int)
    with open(os.path.join(outdir, "shopify", "orders.jsonl"), "w") as shopify, \
            open(os.path.join(outdir, "amazon", "all_orders.txt"), "w", newline="") as amazon:
        amazon_writer = csv.writer(amazon, delimiter="\t", lineterminator="\n")
        amazon_writer.writerow(AMAZON_ORDER_COLUMNS)
        for item in sim.run():
            if isinstance(item, ShopifyOrder) and item.created.astimezone(US_EAST).date() >= YEAR_START:
                _shopify_order(shopify, item)
                counts["shopify_orders"] += 1
            elif isinstance(item, AmazonOrder) and item.purchased.astimezone(US_EAST).date() >= YEAR_START:
                _amazon_order(amazon_writer, item)
                counts["amazon_orders"] += 1
    _shopify_products(outdir, sim)
    _amazon_inventory(outdir, sim)
    _tpl(outdir, sim, rng)
    _quickbooks(outdir, sim)
    counts["pdfs"] = _documents(outdir, sim)
    refs = _wechat(outdir, sim)
    counts["emails"] = _mbox(outdir, sim)
    _truth(outdir, sim, refs)
    counts["wechat_messages"] = sum(1 for m in sim.messages if m.at <= NOW)
    return dict(counts)


def _z(when: datetime) -> str:
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _money(amount: Decimal) -> dict:
    return {"shopMoney": {"amount": f"{amount:.2f}", "currencyCode": "USD"}}


# --- Shopify ------------------------------------------------------------------------------


def _shopify_order(out, o: ShopifyOrder) -> None:
    gid = f"gid://shopify/Order/{o.id}"
    refunded = sum((amount for when, amount in o.refunds if when <= NOW), Decimal(0))
    if o.cancelled and o.cancelled <= NOW:
        financial = "REFUNDED" if o.cancel_reason != "fraud" else "VOIDED"
    elif refunded >= o.total:
        financial = "REFUNDED"
    elif refunded:
        financial = "PARTIALLY_REFUNDED"
    else:
        financial = "PAID"
    fulfilled = o.fulfilled is not None and o.fulfilled <= NOW
    record = {
        "id": gid, "name": o.name, "createdAt": _z(o.created), "processedAt": _z(o.created),
        "updatedAt": _z(min(NOW, max([o.created] + [w for w, _ in o.refunds if w <= NOW]
                                      + ([o.fulfilled] if fulfilled else [])))),
        "cancelledAt": _z(o.cancelled) if o.cancelled and o.cancelled <= NOW else None,
        "cancelReason": o.cancel_reason.upper() if o.cancelled and o.cancelled <= NOW else None,
        "displayFinancialStatus": financial,
        "displayFulfillmentStatus": "FULFILLED" if fulfilled else "UNFULFILLED",
        "currencyCode": "USD", "sourceName": o.source,
        "discountCodes": [o.discount_code] if o.discount_code else [],
        "subtotalPriceSet": _money(o.subtotal), "totalShippingPriceSet": _money(o.shipping),
        "totalTaxSet": _money(o.tax), "totalPriceSet": _money(o.total), "totalRefundedSet": _money(refunded),
        "shippingLine": {"title": f"{o.shipping_method} Shipping"},
        "customer": {"id": f"gid://shopify/Customer/{o.customer.id}", "email": o.customer.person.email,
                     "firstName": o.customer.person.first, "lastName": o.customer.person.last,
                     "phone": o.customer.person.phone},
        "email": o.customer.person.email,
        "shippingAddress": {"name": f"{o.address.first} {o.address.last}", "address1": o.address.address1,
                            "city": o.address.city, "provinceCode": o.address.state, "zip": o.address.zip,
                            "countryCodeV2": "US"},
    }
    out.write(json.dumps(record, ensure_ascii=False) + "\n")
    for line in o.lines:
        sku = line.sku
        out.write(json.dumps({
            "id": f"gid://shopify/LineItem/{line.id}", "sku": sku.shopify_variant_sku,
            "name": f"{sku.family.title} - {sku.variant}", "title": sku.family.title, "variantTitle": sku.variant,
            "quantity": line.quantity, "originalUnitPriceSet": _money(line.price),
            "totalDiscountSet": _money(line.discount), "vendor": catalog.BRAND,
            "variant": {"id": f"gid://shopify/ProductVariant/{sku.shopify_variant_id}"},
            "__parentId": gid}) + "\n")


def _shopify_products(outdir: str, sim: Simulation) -> None:
    with open(os.path.join(outdir, "shopify", "products.jsonl"), "w") as out:
        by_product = defaultdict(list)
        for sku in sim.skus:
            by_product[sku.shopify_product_id].append(sku)
        for product_id, skus in by_product.items():
            family = skus[0].family
            gid = f"gid://shopify/Product/{product_id}"
            out.write(json.dumps({"id": gid, "title": family.title, "handle": family.title.lower().replace(",", "")
                                  .replace(" ", "-"), "vendor": catalog.BRAND, "productType": family.product_type,
                                  "status": "ACTIVE", "createdAt": _z(datetime(2024, 3, 1, 15, tzinfo=US_EAST)
                                                                      if not skus[0].launched else
                                                                      datetime.combine(skus[0].launched,
                                                                                       datetime.min.time(), US_EAST))})
                      + "\n")
            for sku in skus:
                out.write(json.dumps({"id": f"gid://shopify/ProductVariant/{sku.shopify_variant_id}",
                                      "sku": sku.shopify_variant_sku, "title": sku.variant, "barcode": sku.upc,
                                      "price": f"{family.retail:.2f}",
                                      "inventoryQuantity": max(0, sim.stock["3PL-NJ"][sku.code]),
                                      "__parentId": gid}) + "\n")


# --- Amazon -------------------------------------------------------------------------------

AMAZON_ORDER_COLUMNS = ["amazon-order-id", "merchant-order-id", "purchase-date", "last-updated-date", "order-status",
                        "fulfillment-channel", "sales-channel", "order-channel", "ship-service-level", "product-name",
                        "sku", "asin", "item-status", "quantity", "currency", "item-price", "item-tax",
                        "shipping-price", "shipping-tax", "gift-wrap-price", "gift-wrap-tax",
                        "item-promotion-discount", "ship-promotion-discount", "ship-city", "ship-state",
                        "ship-postal-code", "ship-country", "promotion-ids", "is-business-order",
                        "purchase-order-number", "price-designation"]


def _amazon_order(writer, o: AmazonOrder) -> None:
    shipped = o.shipped is not None and o.shipped <= NOW
    status = "Cancelled" if o.cancelled else "Shipped" if shipped else "Pending"
    updated = o.shipped if shipped else o.purchased
    for line in o.lines:
        sku = line.sku
        writer.writerow([o.id, "", o.purchased.isoformat(timespec="seconds"),
                         updated.astimezone(o.purchased.tzinfo).isoformat(timespec="seconds"), status, "Amazon",
                         "Amazon.com", "", o.service_level, f"{FBA_PRODUCT} {sku.family.title} - {sku.variant}",
                         sku.amazon_seller_sku, sku.asin,
                         "Cancelled" if o.cancelled else "Shipped" if shipped else "Unshipped", line.quantity, "USD",
                         "" if o.cancelled else f"{line.item_price:.2f}", "" if o.cancelled else f"{line.item_tax:.2f}",
                         "", "", "", "", f"-{line.promotion_discount:.2f}" if line.promotion_discount else "", "",
                         o.city, o.state, o.zip, "US", line.promotion_id or "", "false", "", ""])


def _amazon_inventory(outdir: str, sim: Simulation) -> None:
    inbound = defaultdict(int)
    for s in sim.fba_shipments:
        if s.status(NOW) != "CLOSED":
            for sku, shipped, _ in s.lines:
                inbound[sku.code] += shipped
    with open(os.path.join(outdir, "amazon", "fba_inventory.txt"), "w", newline="") as out:
        w = csv.writer(out, delimiter="\t", lineterminator="\n")
        w.writerow(["sku", "fnsku", "asin", "product-name", "condition", "your-price", "mfn-listing-exists",
                    "mfn-fulfillable-quantity", "afn-listing-exists", "afn-warehouse-quantity",
                    "afn-fulfillable-quantity", "afn-unsellable-quantity", "afn-reserved-quantity",
                    "afn-total-quantity", "afn-inbound-shipped-quantity"])
        for sku in sim.skus:
            if not sku.asin:
                continue
            on_hand = max(0, sim.stock["FBA-US"][sku.code])
            reserved = min(on_hand, round(on_hand * 0.04))
            w.writerow([sku.amazon_seller_sku, sku.fnsku, sku.asin, f"{FBA_PRODUCT} {sku.title}", "New",
                        f"{sim.amazon_price[sku.code]:.2f}", "No", "", "Yes", on_hand + reserved, on_hand - reserved,
                        0, reserved, on_hand + inbound[sku.code], inbound[sku.code]])
    with open(os.path.join(outdir, "amazon", "fba_inbound_shipments.csv"), "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["Shipment ID", "Shipment name", "Created", "Ship to", "Status", "SKUs", "Units expected",
                    "Units located"])
        for s in sim.fba_shipments:
            if s.created > NOW:
                continue
            w.writerow([s.shipment_id, s.name, f"{s.created:%m/%d/%Y}", s.destination, s.status(NOW), len(s.lines),
                        sum(ln[1] for ln in s.lines),
                        sum(ln[2] for ln in s.lines) if s.status(NOW) == "CLOSED" else 0])


# --- 3PL ----------------------------------------------------------------------------------


def _tpl_description(sku) -> str:
    words = sku.family.title.upper().replace(",", "").split()
    return " ".join(w[:6] for w in words)[:28] + " " + catalog.VARIANT_CODES[sku.variant]


def _tpl(outdir: str, sim: Simulation, rng: random.Random) -> None:
    damaged = defaultdict(int)
    last_receipt = {}
    with open(os.path.join(outdir, "3pl", "receipts.csv"), "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["Receipt #", "ASN #", "Container #", "Reference", "Received Date", "Item Code", "Client SKU",
                    "Description", "Expected", "Received", "Damaged"])
        for r in sim.receipts:
            if r.received_at > NOW:
                continue
            reference = " / ".join(p.number for p in r.shipment.pos) if rng.random() < 0.7 else ""
            for ln in r.lines:
                damaged[ln.sku.code] += ln.damaged
                last_receipt[ln.sku.code] = r.received_at
                w.writerow([r.receipt_no, r.asn_no, r.shipment.container_no or r.shipment.hbl, reference,
                            f"{r.received_at:%m/%d/%Y}", ln.sku.tpl_item_code, ln.sku.tpl_client_sku,
                            _tpl_description(ln.sku), ln.expected, ln.received, ln.damaged])
    with open(os.path.join(outdir, "3pl", "inventory_snapshot.csv"), "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["Item Code", "Client SKU", "Description", "UPC", "Warehouse", "On Hand", "Allocated",
                    "Available", "Damaged", "Last Receipt Date", "Snapshot Time"])
        for sku in sim.skus:
            on_hand = max(0, sim.stock["3PL-NJ"][sku.code])
            allocated = min(on_hand, rng.randint(0, 12))
            w.writerow([sku.tpl_item_code, sku.tpl_client_sku, _tpl_description(sku), sku.upc, "EDISON-NJ",
                        on_hand + allocated, allocated, on_hand, damaged[sku.code],
                        f"{last_receipt[sku.code]:%m/%d/%Y}" if sku.code in last_receipt else "",
                        f"{NOW - timedelta(hours=7):%m/%d/%Y %H:%M}"])
    with open(os.path.join(outdir, "3pl", "outbound.csv"), "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["Ship Date", "Order Reference", "Item Code", "Client SKU", "Qty", "Carrier", "Tracking #"])
        for when, reference, lines, carrier in sim.outbound:
            if when > NOW or when.astimezone(US_EAST).date() < YEAR_START:
                continue
            tracking = _tracking(rng, carrier)
            for sku, qty in lines:
                w.writerow([f"{when:%m/%d/%Y}", reference, sku.tpl_item_code, sku.tpl_client_sku, qty, carrier,
                            tracking])


def _tracking(rng: random.Random, carrier: str) -> str:
    if carrier.startswith("UPS"):
        return "1Z" + "".join(rng.choice("ABCDEFGHJKLMNPRSTUVWXYZ0123456789") for _ in range(16))
    if carrier.startswith("USPS"):
        return "9400" + "".join(str(rng.randint(0, 9)) for _ in range(18))
    return f"PRO {rng.randint(10**8, 10**9 - 1)}"


# --- QuickBooks ---------------------------------------------------------------------------


def _quickbooks(outdir: str, sim: Simulation) -> None:
    bills = [b for b in sim.bills if b.on <= TODAY]
    vendors = {}
    for s in sim.suppliers:
        vendors[s.qb_name] = (s.name, s.currency, s.payment_terms.replace("T/T ", ""), f"sales@{s.code.lower()}.example")
    vendors[catalog.FORWARDER[0]] = (f"{catalog.FORWARDER[0]} Inc", "USD", "Net 15", f"ar@{catalog.FORWARDER[1]}")
    vendors[catalog.BROKER[0]] = (f"{catalog.BROKER[0]} LLC", "USD", "Net 10", f"billing@{catalog.BROKER[1]}")
    vendors["Garden State Fulfillment LLC"] = ("Garden State Fulfillment LLC", "USD", "Net 15",
                                               f"billing@{catalog.TPL[1]}")
    open_balance = defaultdict(Decimal)
    for b in bills:
        if not (b.paid and b.paid <= TODAY):
            open_balance[b.vendor] += b.amount
    with open(os.path.join(outdir, "quickbooks", "vendors.csv"), "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["Vendor", "Company name", "Currency", "Terms", "Email", "Open balance"])
        for name, (company, currency, terms, email) in vendors.items():
            w.writerow([name, company, currency, terms, email, f"{open_balance[name]:.2f}"])
    with open(os.path.join(outdir, "quickbooks", "transaction_list_by_vendor.csv"), "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["Vendor", "Date", "Transaction type", "Num", "Memo/Description", "Account", "Currency",
                    "Exchange rate", "Amount", "Open balance"])
        for b in sorted(bills, key=lambda b: (b.vendor, b.on)):
            paid = b.paid is not None and b.paid <= TODAY
            for account, amount in b.lines:
                w.writerow([b.vendor, f"{b.on:%m/%d/%Y}", "Bill", b.doc_number, b.memo, account, b.currency,
                            b.exchange_rate, f"{amount:.2f}", "0.00" if paid else f"{amount:.2f}"])
            if paid:
                w.writerow([b.vendor, f"{b.paid:%m/%d/%Y}", "Bill Payment (Check)", "", f"Payment {b.doc_number}",
                            "Operating Account (Chase 4471)", b.currency, b.exchange_rate, f"-{b.amount:.2f}", ""])


# --- documents, chat, email ---------------------------------------------------------------


def _documents(outdir: str, sim: Simulation) -> int:
    n = 0
    for doc in sim.documents:
        if doc.issued > TODAY:
            continue
        path = os.path.join(outdir, "supplier_docs", doc.filename)
        if doc.kind == "proforma_invoice":
            documents.proforma_invoice(doc.subject, path)
        elif doc.kind == "commercial_invoice":
            documents.commercial_invoice(*doc.subject, path)
        else:
            documents.qc_report(doc.subject, path)
        n += 1
    return n


def _wechat(outdir: str, sim: Simulation) -> dict:
    """Write one export per supplier chat. Returns each message's reference as file#number."""
    refs = {}
    by_chat = defaultdict(list)
    for i, m in enumerate(sim.messages, 1):
        if m.at <= NOW:
            by_chat[m.chat].append((i, m))
    for supplier in sim.suppliers:
        filename = f"{supplier.code}_{supplier.sales.split()[0]}.txt"
        with open(os.path.join(outdir, "wechat", filename), "w", encoding="utf-8") as out:
            out.write(f"微信聊天记录 / WeChat chat history: {supplier.sales_wechat}\n")
            out.write(f"导出时间 Exported: {NOW:%Y-%m-%d %H:%M}\n\n")
            for n, (i, m) in enumerate(sorted(by_chat[supplier.code], key=lambda x: x[1].at), 1):
                out.write(f"{m.at.astimezone(US_EAST):%Y-%m-%d %H:%M:%S} {m.sender}\n{m.text}\n\n")
                refs[f"wechat:{supplier.code}:{i}"] = f"wechat/{filename}#{n}"
    return refs


def _mbox(outdir: str, sim: Simulation) -> int:
    emails = sorted((e for e in sim.emails if e.at <= NOW), key=lambda e: e.at)
    with open(os.path.join(outdir, "email", "ops_inbox.mbox"), "w", encoding="utf-8") as out:
        for e in emails:
            out.write(f"From {e.sender[1]} {e.at.astimezone(US_EAST):%a %b %d %H:%M:%S %Y}\n")
            out.write(f"From: {e.sender[0]} <{e.sender[1]}>\nTo: {e.to[0]} <{e.to[1]}>\n")
            out.write(f"Subject: {e.subject}\nDate: {format_datetime(e.at.astimezone(US_EAST))}\n")
            out.write(f"Message-ID: {e.message_id}\nMIME-Version: 1.0\n")
            out.write("Content-Type: text/plain; charset=utf-8\n")
            if e.attachments:
                out.write(f"X-Attachments: {', '.join(e.attachments)}\n")
            out.write("\n")
            for line in (e.body + "\n\nThis email and any attachments are confidential and intended solely for the "
                                  "addressee.").splitlines():
                out.write((">" + line if line.startswith("From ") else line) + "\n")
            out.write("\n")
    return len(emails)


# --- ground truth -------------------------------------------------------------------------


def _truth(outdir: str, sim: Simulation, wechat_refs: dict) -> None:
    with open(os.path.join(outdir, "truth", "crosswalk.csv"), "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["sku", "upc", "supplier", "factory_code", "hs_code", "shopify_variant_id", "shopify_variant_sku",
                    "amazon_seller_sku", "asin", "fnsku", "tpl_item_code", "tpl_client_sku"])
        for k in sim.skus:
            w.writerow([k.code, k.upc, k.supplier.code, k.factory_code, k.family.hs_code, k.shopify_variant_id,
                        k.shopify_variant_sku, k.amazon_seller_sku or "", k.asin or "", k.fnsku or "",
                        k.tpl_item_code, k.tpl_client_sku])
    with open(os.path.join(outdir, "truth", "vendors.csv"), "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["supplier_code", "legal_name", "quickbooks_vendor", "wechat_contact"])
        for s in sim.suppliers:
            w.writerow([s.code, s.name, s.qb_name, s.sales_wechat])
    with open(os.path.join(outdir, "truth", "duplicate_customers.csv"), "w", newline="") as out:
        w = csv.writer(out)
        w.writerow(["customer_id", "same_person_as"])
        for c in sim.customers:
            if c.duplicate_of:
                w.writerow([c.id, c.duplicate_of])
    with open(os.path.join(outdir, "truth", "statements.jsonl"), "w", encoding="utf-8") as out:
        for s in sorted(sim.statements, key=lambda s: s.at):
            if s.at > NOW:
                continue
            ref = wechat_refs.get(s.ref, s.ref) if s.source == "wechat" else (
                f"supplier_docs/{s.ref}" if s.source == "pdf" else f"email/ops_inbox.mbox {s.ref}")
            out.write(json.dumps({"source": s.source, "ref": ref, "at": s.at.isoformat(), "subject": s.subject,
                                  "field": s.field, "value": s.value}, ensure_ascii=False) + "\n")
    with open(os.path.join(outdir, "truth", "shapes.json"), "w") as out:
        json.dump(vocabulary.SHAPES, out, indent=2)
    with open(os.path.join(outdir, "truth", "README.md"), "w") as out:
        out.write(TRUTH_README)


TRUTH_README = """# Ground truth

What the exports mean, for scoring skills that read them.

- `crosswalk.csv`: every SKU under each system's code. Shopify variant SKUs and the 3PL's
  client SKUs are sometimes reformatted, blank or mistyped; this file has the true mapping.
  Factory codes repeat across factories, so they only identify an item together with the supplier.
- `vendors.csv`: each supplier's legal name, QuickBooks vendor name and WeChat contact.
- `duplicate_customers.csv`: Shopify customer accounts that are the same person.
- `statements.jsonl`: facts asserted in the PDFs, chats and emails: ETDs and their changes, PI
  numbers, unit prices, inspection results, container numbers, ETAs, duty totals, receiving
  damage, price changes and holiday closures. `ref` points at the file, and for chats the message
  number. Chat timestamps are in the ops manager's time zone (New York), while suppliers write
  dates in China time.
- `shapes.json`: the kinds of thing the direct loader writes, with the attributes each carries.
"""
