"""The vocabulary the loader writes with. The store-primary side comes from the packages:
factstore-core, which init installs, and factstore-ecom-ops (ECOM_OPS), which the loader needs
installed. The loader registers CATALOGUE itself: the sales-side identifiers Shopify, Amazon and
the 3PL own, which the catalogue skill would register on its first run. They are the attributes
registered beyond the package (build plan M5).

Where the kernel's near-match check flags two attributes that really are different, the later
one lists the earlier in distinct_from, as the packages' manifests do.
"""

from pathlib import Path

ECOM_OPS = Path(__file__).resolve().parents[3] / "packages" / "ecom-ops"


def a(ident, type_, cardinality="one", doc="", unique="none"):
    return {"ident": ident, "type": type_, "cardinality": cardinality, "doc": doc, "unique": unique,
            "distinct_from": DISTINCT_FROM.get(ident, [])}


# Pairs the kernel's near-match check flags in the catalogue's attributes, judged genuinely different.
DISTINCT_FROM = {
    "shopify/line_item_id": ["shopify/order_id"],
    "amazon/order_id": ["shopify/order_id"],
    "amazon/order_line": ["amazon/order_id"],
    "order/customer": ["shopify/customer_id"],
    "line/sku": ["po_line/sku"],
}


CATALOGUE = [
    a("shopify/order_id", "string", "one", "Shopify's ID for an order.", "identity"),
    a("shopify/customer_id", "string", "one", "Shopify's ID for a customer account.", "identity"),
    a("shopify/line_item_id", "string", "one", "Shopify's ID for one line of an order.", "identity"),
    a("amazon/order_id", "string", "one", "Amazon's ID for an order, e.g. 113-1234567-1234567.", "identity"),
    a("amazon/order_line", "string", "one", "One item line of an Amazon order, as order ID / seller SKU.", "identity"),
    a("amazon/fba_shipment_id", "string", "one", "Amazon's ID for an inbound shipment of our stock to FBA.", "identity"),
    a("amazon/fba_line", "string", "one", "One SKU in an FBA inbound shipment, as shipment ID / seller SKU.", "identity"),
    a("tpl/receipt_no", "string", "one", "The 3PL's receipt number for goods it booked in.", "identity"),
    a("order/customer", "ref", "one", "Customer account that placed an order."),
    a("line/sku", "ref", "one", "SKU on a sales or transfer line."),
    a("receipt/shipment", "ref", "one", "Shipment a warehouse receipt booked in."),
]


# Ground truth for the ontology skill: the kinds of thing the loader writes and the attributes
# each carries. "always" is on every entity of the shape; "often" on some.
SHAPES = {
    "Supplier": {"always": ["supplier/code", "supplier/name", "supplier/name_cn", "supplier/address", "supplier/port",
                            "supplier/currency", "supplier/payment_terms", "supplier/incoterm",
                            "supplier/contact_name"]},
    "SKU": {"always": ["sku/code", "sku/title", "sku/family", "sku/supplier", "sku/hs_code", "sku/upc",
                       "sku/retail_price", "core/currency", "factory/item_code", "tpl/item_code",
                       "shopify/variant_id"],
            "often": ["amazon/asin", "amazon/fnsku", "amazon/seller_sku", "sku/launched_on"]},
    "Location": {"always": ["location/code", "location/name", "location/kind"]},
    "Purchase order": {"always": ["po/number", "po/supplier", "po/status", "po/placed_on", "core/currency"],
                       "often": ["po/pi_number", "po/etd"]},
    "Purchase order line": {"always": ["po_line/key", "core/part_of", "po_line/sku", "po_line/quantity"],
                            "often": ["po_line/unit_price"]},
    "QC inspection": {"always": ["qc/report_no", "qc/po", "qc/inspected_on", "qc/result", "qc/inspector",
                                 "qc/sample_size"]},
    "Shipment": {"always": ["shipment/booking_no", "shipment/hbl", "shipment/mode", "shipment/status",
                            "shipment/origin", "shipment/destination", "shipment/vessel", "shipment/etd",
                            "shipment/eta", "shipment/freight_cost", "core/currency"],
                 "often": ["shipment/container_no", "shipment/delivered_at"]},
    "Shipment line": {"always": ["shipment_line/key", "core/part_of", "shipment_line/po_line",
                                 "shipment_line/quantity", "shipment_line/cartons"]},
    "Customs entry": {"always": ["customs/entry_no", "customs/shipment", "customs/filed_on", "customs/entered_value",
                                 "customs/duty", "customs/fees", "core/currency"]},
    "Stock position": {"always": ["inventory/position", "inventory/sku", "inventory/location"],
                       "often": ["inventory/quantity", "inventory/counted_at"]},
    "Warehouse receipt": {"always": ["tpl/receipt_no", "receipt/shipment"]},
    "Shopify customer": {"always": ["shopify/customer_id"], "often": ["core/same_as"]},
    "Shopify order": {"always": ["shopify/order_id", "order/customer"]},
    "Shopify order line": {"always": ["shopify/line_item_id", "core/part_of", "line/sku"]},
    "Amazon order": {"always": ["amazon/order_id"]},
    "Amazon order line": {"always": ["amazon/order_line", "core/part_of", "line/sku"]},
    "FBA inbound shipment": {"always": ["amazon/fba_shipment_id"]},
    "FBA inbound line": {"always": ["amazon/fba_line", "core/part_of", "line/sku"]},
}
