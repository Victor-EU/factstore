"""Supplier documents as PDFs: proforma invoices, commercial invoices with packing lists,
and third-party inspection reports. Laid out the way Chinese factories and inspection
agencies lay them out: bilingual letterhead, the factory's own item codes and wording,
bank details, and terms."""

import zlib
from decimal import Decimal

from . import catalog
from .clock import cny_per_usd
from .model import Po, QcInspection, Shipment
from .pdf import Document, fit

BANKS = {"USD": "Zhejiang Harbour Commercial Bank, {city} Branch", "CNY": "Zhejiang Harbour Commercial Bank"}


def _letterhead(page, supplier, title: str, title_cn: str) -> float:
    page.text(40, 800, supplier.name_cn, 14)
    page.text(40, 783, supplier.name.upper(), 11, bold=True)
    page.text(40, 770, supplier.address, 8)
    page.text(40, 759, f"Tel: +86 574 5550 {zlib.crc32(supplier.code.encode()) % 9000 + 1000}   "
                       f"Email: sales@{supplier.code.lower()}.example", 8)
    page.line(40, 752, 555, 752, 1)
    page.text(220, 732, f"{title}  {title_cn}", 13, bold=True)
    return 712


def _table(page, y: float, headers: list[tuple[str, float]], rows: list[list], sub: list[str] | None = None) -> float:
    """A ruled table. A cell may be (text, second line), the way factories put the Chinese name under the English."""
    xs = [40]
    for _, w in headers:
        xs.append(xs[-1] + w)
    page.line(40, y + 12, xs[-1], y + 12)
    for (header, w), x in zip(headers, xs):
        page.text(x + 3, y, fit(header, w - 5, 8), 8, bold=True)
    page.line(40, y - 4, xs[-1], y - 4)
    y -= 16
    for row in rows:
        second = False
        for cell, x, (_, w) in zip(row, xs, headers):
            main, extra = cell if isinstance(cell, tuple) else (cell, None)
            page.text(x + 3, y, fit(main, w - 5, 8), 8)
            if extra:
                page.text(x + 3, y - 10, fit(extra, w - 5, 7), 7)
                second = True
        y -= 24 if second else 14
    page.line(40, y + 8, xs[-1], y + 8)
    return y - 6


def _description(sku) -> tuple[str, str]:
    """The factory's wording: English first, Chinese beneath."""
    cn, en = sku.factory_description.split(" / ")
    return en, cn


def proforma_invoice(po: Po, path: str) -> None:
    supplier, rate = po.supplier, None
    doc = Document(f"Proforma Invoice {po.pi_number}")
    page = doc.page()
    y = _letterhead(page, supplier, "PROFORMA INVOICE", "形式发票")
    page.text(40, y, f"Buyer: {catalog.BRAND_LEGAL}", 9)
    page.text(330, y, f"PI No.: {po.pi_number}", 9, bold=True)
    page.text(40, y - 13, catalog.BRAND_ADDRESS, 8)
    page.text(330, y - 13, f"Date: {po.pi_date:%Y-%m-%d}", 9)
    page.text(330, y - 26, f"Your PO: {po.number}", 9)
    page.text(40, y - 26, f"Attn: {catalog.BRAND_OPS[0]}", 8)
    symbol = "USD" if po.currency == "USD" else "RMB"
    rows = [[sku.factory_code, _description(sku), f"{line.quantity:,}", f"{line.cartons}",
             f"{symbol} {line.unit_price:,.2f}", f"{symbol} {line.amount:,.2f}"]
            for line in po.lines for sku in [line.sku]]
    y = _table(page, y - 52, [("Item No.", 62), ("Description 品名", 210), ("Qty (pcs)", 58), ("Ctns", 38),
                              ("Unit Price", 70), ("Amount", 77)], rows)
    page.text(340, y, f"TOTAL {symbol} {po.total:,.2f}", 10, bold=True)
    y -= 26
    terms = [f"1. Price term: {supplier.incoterm}",
             f"2. Payment: {supplier.payment_terms}",
             f"3. Delivery: about {po.quoted_etd:%b %d, %Y} (ETD), subject to deposit received",
             "4. Packing: export carton, shipping marks per buyer's instruction",
             f"5. Total volume approx. {po.cbm:.2f} CBM"]
    if po.currency == "CNY":
        rate = cny_per_usd(po.pi_date)
        terms.append(f"6. For reference: about USD {po.total / rate:,.2f} at {rate} RMB/USD")
    for t in terms:
        page.text(40, y, t, 9)
        y -= 13
    y -= 8
    page.text(40, y, "Bank information 银行信息:", 9, bold=True)
    bank = BANKS[po.currency].format(city=supplier.port)
    for t in (f"Beneficiary: {supplier.name}", f"Bank: {bank}", f"A/C No.: 3301 0400 {zlib.crc32(po.supplier.code.encode()) % 10**8:08d}",
              "SWIFT: ZHCBCNBJXXX (illustrative)"):
        y -= 13
        page.text(52, y, t, 8)
    page.text(40, 90, "Seller 卖方:", 9)
    page.text(330, 90, "Buyer 买方:", 9)
    page.text(40, 70, f"{supplier.sales} (signed and stamped) 盖章", 8)
    doc.save(path)


def commercial_invoice(shipment: Shipment, po: Po, path: str) -> None:
    supplier = po.supplier
    doc = Document(f"Commercial Invoice and Packing List {po.pi_number}")
    lines = [sl for sl in shipment.lines if sl.po_line.po is po]
    symbol = "USD" if po.currency == "USD" else "RMB"
    page = doc.page()
    y = _letterhead(page, supplier, "COMMERCIAL INVOICE", "商业发票")
    page.text(40, y, f"Sold to: {catalog.BRAND_LEGAL}, {catalog.BRAND_ADDRESS}", 8)
    page.text(40, y - 13, f"Invoice No.: CI-{po.pi_number}   Date: {shipment.etd:%Y-%m-%d}   Order: {po.number}", 9)
    page.text(40, y - 26, f"From {shipment.origin} to {shipment.destination} by sea, {shipment.vessel} {shipment.voyage}"
                          f"   Container: {shipment.container_no or 'LCL'}   B/L: {shipment.hbl}", 8)
    rows = [[sl.po_line.sku.factory_code, _description(sl.po_line.sku), sl.po_line.sku.family.hs_code,
             f"{sl.quantity:,}", f"{symbol} {sl.po_line.unit_price:,.2f}",
             f"{symbol} {sl.quantity * sl.po_line.unit_price:,.2f}"] for sl in lines]
    y = _table(page, y - 52, [("Item No.", 62), ("Description", 196), ("HS Code", 68), ("Qty", 50), ("Unit", 68),
                              ("Amount", 71)], rows)
    total = sum((sl.quantity * sl.po_line.unit_price for sl in lines), Decimal(0))
    page.text(330, y, f"TOTAL {supplier.incoterm} {symbol} {total:,.2f}", 9, bold=True)
    page.text(40, y - 20, "Country of origin: China. We certify this invoice is true and correct.", 8)

    page = doc.page()
    y = _letterhead(page, supplier, "PACKING LIST", "装箱单")
    page.text(40, y, f"Invoice No.: CI-{po.pi_number}   Container: {shipment.container_no or 'LCL'}   "
                     f"Seal: {shipment.seal_no or '-'}", 9)
    rows = []
    carton_no = 1
    for sl in lines:
        carton = sl.po_line.sku.family.carton
        rows.append([f"{carton_no}-{carton_no + sl.cartons - 1}", sl.po_line.sku.factory_code, f"{sl.cartons}",
                     f"{carton.units}", f"{sl.quantity:,}", f"{carton.gross_kg * sl.cartons:,.1f}",
                     f"{carton.length_cm}x{carton.width_cm}x{carton.height_cm}", f"{carton.cbm * sl.cartons:.2f}"])
        carton_no += sl.cartons
    y = _table(page, y - 30, [("Ctn No.", 70), ("Item No.", 62), ("Ctns", 40), ("Pcs/Ctn", 50), ("Total Pcs", 60),
                              ("G.W. kg", 60), ("Meas. cm", 90), ("CBM", 50)], rows)
    page.text(40, y, f"TOTAL: {sum(sl.cartons for sl in lines)} CTNS", 9, bold=True)
    page.text(40, y - 16, f"Shipping marks: ACME HEARTH / {po.number} / C/NO. 1-UP / MADE IN CHINA", 8)
    doc.save(path)


def qc_report(qc: QcInspection, path: str) -> None:
    po = qc.po
    doc = Document(f"Inspection Report {qc.report_no}")
    page = doc.page()
    page.text(40, 800, qc.inspector.upper(), 13, bold=True)
    page.text(40, 785, "Pre-Shipment Inspection Report", 11)
    page.line(40, 778, 555, 778, 1)
    fields = [("Report No.", qc.report_no), ("Inspection date", f"{qc.on:%Y-%m-%d}"),
              ("Client", catalog.BRAND_LEGAL), ("Supplier", po.supplier.name), ("PO No.", po.number),
              ("Sampling", f"ISO 2859-1, Level II, AQL Critical 0 / Major 2.5 / Minor 4.0, sample size {qc.sample_size}"),
              ("Overall result", qc.result)]
    y = 758
    for label, value in fields:
        page.text(40, y, f"{label}:", 9, bold=True)
        page.text(150, y, value, 9, bold=label == "Overall result")
        y -= 15
    y = _table(page, y - 14, [("Item No.", 70), ("Description", 250), ("Order Qty", 70), ("Inspected", 70)],
               [[ln.sku.factory_code, _description(ln.sku), f"{ln.quantity:,}",
                 f"{min(ln.quantity, qc.sample_size)}"] for ln in po.lines])
    y = _table(page, y - 10, [("Defect found", 300), ("Severity", 80), ("Qty", 60)],
               [[text, severity, str(count)] for text, severity, count in qc.defects])
    conclusion = ("Goods conform to the client's requirements. Released for shipment."
                  if qc.result == "PASS" else
                  "Major defects exceed the acceptance number. Goods NOT released; rework and re-inspection required.")
    page.text(40, y - 6, conclusion, 9)
    page.text(40, 80, "This report reflects the samples inspected only.", 7)
    doc.save(path)
