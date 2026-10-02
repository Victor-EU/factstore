import sys,json,csv,re
from common import *
dry='--go' not in sys.argv
sk=json.load(open('skutx.json'))
s2h={f['v']:f['e'][1] for f in sk['tx4']+sk['tx5'] if f['a']=='amazon/seller_sku'}
t2h={f['v']:f['e'][1] for f in sk['tx3']}
A=list(csv.DictReader(open(EX+'amazon/all_orders.txt'),delimiter='\t'))
af=[];seen=set()
for a in A:
    o=a['amazon-order-id']
    if o not in seen:
        seen.add(o); af+=[{"e":["amazon/order_id",o],"a":"amazon/order_id","v":o}]
    k=f"{o}/{a['sku']}"; e=["amazon/order_line_key",k]
    af+=[{"e":e,"a":"amazon/order_line_key","v":k},{"e":e,"a":"core/part_of","v":["amazon/order_id",o]},{"e":e,"a":"line/sku","v":["sku/code",s2h[a['sku']]]}]
F=list(csv.DictReader(open(EX+'amazon/fba_inbound_shipments.csv')))
ff=[{"e":["amazon/fba_shipment_id",r['Shipment ID']],"a":"amazon/fba_shipment_id","v":r['Shipment ID']} for r in F]
R=list(csv.DictReader(open(EX+'3pl/receipts.csv')))
rf=[];seen=set()
for r in R:
    n=r['Receipt #']; e=["tpl/receipt_no",n]
    if n not in seen:
        seen.add(n); rf.append({"e":e,"a":"tpl/receipt_no","v":n})
        for po in [p.strip() for p in r['Reference'].split('/') if p.strip()]:
            assert re.fullmatch(r'PO-\d{4}-\d{4}',po),po
            rf.append({"e":e,"a":"receipt/po","v":["po/number",po]})
    k=f"{n}/{r['Item Code']}"; le=["tpl/receipt_line_key",k]
    rf+=[{"e":le,"a":"tpl/receipt_line_key","v":k},{"e":le,"a":"core/part_of","v":e},{"e":le,"a":"line/sku","v":["sku/code",t2h[r['Item Code']]]}]
print(len(seen),len(rf),len(af),len(ff))
if not dry:
    for facts,rels in [(ff,['amazon/fba_inbound_shipments.csv']),(af,['amazon/all_orders.txt']),(rf,['3pl/receipts.csv'])]:
        for r in write(facts,rels,None,chunk=5000): print(r.tx)
