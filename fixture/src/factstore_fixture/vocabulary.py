"""The vocabulary the loader writes with comes from the packages: factstore-core, which init
installs, factstore-ecom-ops (ECOM_OPS) for the supply side the store is primary for, and
factstore-ecom-index (ECOM_INDEX) for the identifiers of the records Shopify, Amazon and the 3PL
own. The loader registers nothing itself.
"""

from pathlib import Path

PACKAGES = Path(__file__).resolve().parents[3] / "packages"
ECOM_OPS = PACKAGES / "ecom-ops"
ECOM_INDEX = PACKAGES / "ecom-index"


# Ground truth for the ontology skill: the kinds of thing the loader writes and the attributes
# each carries. "always" is on every entity of the shape; "often" on some. Stock is not a kind:
# it is derived from POs and shipment lines (design §14).
SHAPES = {
    "Supplier": {"always": ["supplier/code", "supplier/name", "supplier/name_cn", "supplier/address", "supplier/port",
                            "supplier/currency", "supplier/payment_terms", "supplier/incoterm",
                            "supplier/contact_name"]},
    "SKU": {"always": ["sku/code", "sku/title", "sku/family", "sku/supplier", "sku/hs_code", "sku/upc",
                       "sku/retail_price", "core/currency", "factory/item_code", "tpl/item_code",
                       "shopify/variant_id"],
            "often": ["amazon/asin", "amazon/fnsku", "amazon/seller_sku", "sku/launched_on"]},
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
    "Warehouse receipt": {"always": ["tpl/receipt_no", "receipt/po"]},
    "Shopify customer": {"always": ["shopify/customer_id"], "often": ["core/same_as"]},
    "Shopify order": {"always": ["shopify/order_id", "order/customer"]},
    "Shopify order line": {"always": ["shopify/line_item_id", "core/part_of", "line/sku"]},
    "Amazon order": {"always": ["amazon/order_id"]},
    "Amazon order line": {"always": ["amazon/order_line", "core/part_of", "line/sku"]},
    "FBA inbound shipment": {"always": ["amazon/fba_shipment_id"]},
    "FBA inbound line": {"always": ["amazon/fba_line", "core/part_of", "line/sku"]},
}
