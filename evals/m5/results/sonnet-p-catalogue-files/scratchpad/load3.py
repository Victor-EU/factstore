from common import *
prod,vs=products()
upc={v['barcode']:hub(v['sku']) for v in vs}
tp=list(csv.DictReader(open(W+'3pl/inventory_snapshot.csv')))
i2h={r['Item Code']:upc[r['UPC']] for r in tp}
# receipts
rc=list(csv.DictReader(open(W+'3pl/receipts.csv')))
G=[];seen=set()
for r in rc:
    re_=["tpl/receipt_no",r['Receipt #']]
    k=r['Receipt #']+'/'+r['Item Code']; assert k not in seen; seen.add(k)
    le=["tpl/receipt_line",k]
    g=[{"e":le,"a":"core/part_of","v":re_},{"e":le,"a":"line/sku","v":["sku/code",i2h[r['Item Code']]]}]
    for p in [x.strip() for x in r['Reference'].split('/') if x.strip()]:
        assert re.match(r'^PO-20\d\d-\d{4}$',p)
        g.append({"e":re_,"a":"receipt/po","v":["po/number",p]})
    G.append(g)
batched(G,['3pl/receipts.csv','3pl/inventory_snapshot.csv'])
# FBA shipments
sh=list(csv.DictReader(open(W+'amazon/fba_inbound_shipments.csv')))
tx([{"e":["amazon/fba_shipment_id",r['Shipment ID']],"a":"amazon/fba_shipment_id","v":r['Shipment ID']} for r in sh],'amazon/fba_inbound_shipments.csv')
# outbound
ob=list(csv.DictReader(open(W+'3pl/outbound.csv')))
G=[];seen=set()
for r in ob:
    ref=r['Order Reference']
    k=ref+'/'+r['Item Code']; assert k not in seen; seen.add(k)
    whole=["amazon/fba_shipment_id",ref] if ref.startswith('FBA') else ["shopify/order_name",ref]
    if not ref.startswith('FBA'): assert re.match(r'^#\d+$',ref)
    le=["tpl/outbound_line",k]
    G.append([{"e":le,"a":"core/part_of","v":whole},{"e":le,"a":"line/sku","v":["sku/code",i2h[r['Item Code']]]}])
batched(G,['3pl/outbound.csv','3pl/inventory_snapshot.csv'],size=4000)
# amazon orders
inv=list(csv.DictReader(open(W+'amazon/fba_inventory.txt'),delimiter='\t'))
listings={r['sku'] for r in inv}
o=list(csv.DictReader(open(W+'amazon/all_orders.txt'),delimiter='\t'))
G=[];seen=set()
for r in o:
    oid=r['amazon-order-id']; assert re.match(r'^\d{3}-\d{7}-\d{7}$',oid) and r['sku'] in listings
    k=oid+'/'+r['sku']
    if k in seen: continue
    seen.add(k)
    le=["amazon/order_line",k]
    G.append([{"e":le,"a":"core/part_of","v":["amazon/order_id",oid]},{"e":le,"a":"line/listing","v":["amazon/seller_sku",r['sku']]}])
print(len(seen))
batched(G,'amazon/all_orders.txt',size=4000)
