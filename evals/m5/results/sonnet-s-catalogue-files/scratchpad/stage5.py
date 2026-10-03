from common import *
A={'shopify':['shopify/customer_id','shopify/line_item_id','shopify/order_id','shopify/order_name','shopify/variant_id'],
'amazon':['amazon/asin','amazon/fba_shipment_id','amazon/fnsku','amazon/order_id','amazon/order_line','amazon/seller_sku'],
'3pl':['tpl/item_code','tpl/outbound_line','tpl/receipt_line','tpl/receipt_no'],
'quickbooks':['quickbooks/vendor']}
f=[{'e':['fs/ident',a],'a':'core/authoritative_source','v':s} for s,l in A.items() for a in l]
print(factstore.transact(f).__dict__ if hasattr(factstore.transact(f),'__dict__') else 'ok')
