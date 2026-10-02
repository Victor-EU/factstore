import factstore
A={'shopify':['shopify/variant_id','shopify/sku','shopify/order_id','shopify/order_name','shopify/customer_id','order/customer'],
'amazon':['amazon/asin','amazon/fnsku','amazon/seller_sku','amazon/order_id','amazon/fba_shipment_id'],
'3pl':['tpl/item_code','tpl/client_sku','tpl/receipt_no','tpl/asn_no','tpl_receipt/shipment'],
'quickbooks':['quickbooks/vendor_name']}
f=[{'e':['fs/ident',a],'a':'core/authoritative_source','v':s} for s,l in A.items() for a in l]
print(factstore.transact(f).tx)
