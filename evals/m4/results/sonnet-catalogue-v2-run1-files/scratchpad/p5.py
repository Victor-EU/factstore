from load import *
# ---- Amazon orders and lines
az=list(csv.DictReader(open(X+'amazon/all_orders.txt'),delimiter='\t'))
f=[]
for r in az:
    o=["amazon/order_id",r['amazon-order-id']]; k=["amazon/order_line_key",r['amazon-order-id']+'/'+r['sku']]
    f+=[{"e":k,"a":"core/part_of","v":o},{"e":k,"a":"line/sku","v":["amazon/seller_sku",r['sku']]}]
print('amazon lines',len(az),tx(f,'amazon/all_orders.txt'))
# ---- Amazon FBA inbound shipments
fb=[r['Shipment ID'] for r in csv.DictReader(open(X+'amazon/fba_inbound_shipments.csv'))]
assert len(set(fb))==len(fb)
print('fba shipments',tx([{"e":["amazon/fba_shipment_id",i],"a":"amazon/fba_shipment_id","v":i} for i in fb],'amazon/fba_inbound_shipments.csv'))
# ---- 3PL outbound parcels -> shopify order by name
ob=list(csv.DictReader(open(X+'3pl/outbound.csv')))
par={}
for r in ob:
    t=r['Tracking #']; assert par.setdefault(t,r['Order Reference'])==r['Order Reference']
names={json.loads(l)['name'] for l in open(X+'shopify/orders.jsonl') if '/Order/' in l[:60]}
miss=[o for o in par.values() if o not in names]; print('outbound refs not in shopify',len(miss),miss[:5])
fbs=set(fb)
assert all(o in names or o in fbs for o in par.values())
f=[{"e":["tpl/outbound_tracking_no",t],"a":"tpl/outbound_order","v":["shopify/order_name",o]} for t,o in par.items() if o in names]
f+=[{"e":["tpl/outbound_tracking_no",t],"a":"tpl/outbound_fba_shipment","v":["amazon/fba_shipment_id",o]} for t,o in par.items() if o in fbs]
print('outbound',len(f),tx(f,'3pl/outbound.csv'))
# ---- 3PL receipts -> PO
rc=list(csv.DictReader(open(X+'3pl/receipts.csv')))
rp={}
for r in rc: assert rp.setdefault(r['Receipt #'],r['Reference'])==r['Reference']
f=[{"e":["tpl/receipt_no",k],"a":"tpl/receipt_po","v":["po/number",v]} for k,v in rp.items()]
print('receipts',len(f),tx(f,'3pl/receipts.csv'))
