from common import *
# Amazon orders
ao=list(csv.DictReader(open(P+'amazon/all_orders.txt'),delimiter='\t'))
orders=[];lines=[];seen=set()
for r in ao:
    oid=r['amazon-order-id']; assert re.match(r'^\d{3}-\d{7}-\d{7}$',oid)
    if oid not in seen: seen.add(oid); orders.append({"e":["amazon/order_id",oid],"a":"amazon/order_id","v":oid})
    k=f"{oid}/{r['sku']}"
    lines+=[{"e":["amazon/order_line",k],"a":"amazon/order_line","v":k},{"e":["amazon/order_line",k],"a":"core/part_of","v":["amazon/order_id",oid]},{"e":["amazon/order_line",k],"a":"line/sku","v":sku(norm(r['sku']))}]
S=['amazon/all_orders.txt']
write(orders,S,label='amz orders'); write(lines,S,label='amz lines')
# 3PL
inv=rd('3pl/inventory_snapshot.csv'); i2s={r['Item Code']:r['Item Code'] for r in inv}
upc2c={r['v']:r['e'] for r in []}
V=variants(); upc2sku={v['barcode']:norm(v['sku']) for v in V}
item2sku={r['Item Code']:upc2sku[r['UPC']] for r in inv}
rc=rd('3pl/receipts.csv'); rf=[];rl=[];recs={}
for r in rc:
    n=r['Receipt #']; recs.setdefault(n,set()).update(p.strip() for p in r['Reference'].split('/') if p.strip())
print('PO refs:',sorted({p for s in recs.values() for p in s}))
for p in {p for s in recs.values() for p in s}: assert re.match(r'^PO-20\d\d-\d{4}$',p),p
for n,ps in recs.items():
    rf.append({"e":["tpl/receipt_no",n],"a":"tpl/receipt_no","v":n})
    for p in sorted(ps): rf.append({"e":["tpl/receipt_no",n],"a":"receipt/po","v":["po/number",p]})
for r in rc:
    k=f"{r['Receipt #']}/{r['Item Code']}"
    rl+=[{"e":["tpl/receipt_line",k],"a":"tpl/receipt_line","v":k},{"e":["tpl/receipt_line",k],"a":"core/part_of","v":["tpl/receipt_no",r['Receipt #']]},{"e":["tpl/receipt_line",k],"a":"line/sku","v":sku(item2sku[r['Item Code']])}]
S=['3pl/receipts.csv','3pl/inventory_snapshot.csv']
write(rf,S,label='receipts'); write(rl,S,label='receipt lines')
ob=rd('3pl/outbound.csv'); ol=[]
for r in ob:
    k=f"{r['Order Reference']}/{r['Item Code']}"
    ref=r['Order Reference']
    whole=["amazon/fba_shipment_id",ref] if ref.startswith('FBA') else ["shopify/order_name",ref]
    ol+=[{"e":["tpl/outbound_line",k],"a":"tpl/outbound_line","v":k},{"e":["tpl/outbound_line",k],"a":"core/part_of","v":whole},{"e":["tpl/outbound_line",k],"a":"line/sku","v":sku(item2sku[r['Item Code']])}]
write(ol,['3pl/outbound.csv','3pl/inventory_snapshot.csv'],label='outbound')
