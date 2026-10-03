from common import *
hubs={r[0] for r in factstore.query('select v from "sku/code"').rows}
print('hubs',len(hubs))
fi=list(csv.DictReader(open(EX+'/amazon/fba_inventory.txt'),delimiter='\t'))
ex=[];nm=[];un=[]
for r in fi:
    s=r['sku']; l=["amazon/seller_sku",s]
    fs=[{"e":l,"a":"amazon/seller_sku","v":s},{"e":l,"a":"amazon/fnsku","v":r['fnsku']},
        {"e":["amazon/asin",r['asin']],"a":"amazon/asin","v":r['asin']},{"e":l,"a":"listing/asin","v":["amazon/asin",r['asin']]}]
    if s in hubs: ex+=fs+[{"e":l,"a":"listing/sku","v":["sku/code",s]}]
    elif re.sub(r'-FBA$','',s) in hubs: nm+=fs+[{"e":l,"a":"listing/sku","v":["sku/code",re.sub(r'-FBA$','',s)]}]
    else: un.append(s)
print('unmatched listings',un)
write(ex,'amazon/fba_inventory.txt',1,label='listings exact')
write(nm,'amazon/fba_inventory.txt',0.9,label='listings -FBA suffix')
fb=list(csv.DictReader(open(EX+'/amazon/fba_inbound_shipments.csv')))
write([{"e":["amazon/fba_shipment_id",r['Shipment ID']],"a":"amazon/fba_shipment_id","v":r['Shipment ID']} for r in fb],'amazon/fba_inbound_shipments.csv',None,label='fba shipments')
am=list(csv.DictReader(open(EX+'/amazon/all_orders.txt'),delimiter='\t'))
known={r['sku'] for r in fi}
print('order skus not in listings',{r['sku'] for r in am}-known)
f=[];seen=set()
for r in am:
    o=r['amazon-order-id']; k=f"{o}/{r['sku']}"
    if o not in seen: seen.add(o); f.append({"e":["amazon/order_id",o],"a":"amazon/order_id","v":o})
    f+=[{"e":["amazon/order_line",k],"a":"amazon/order_line","v":k},{"e":["amazon/order_line",k],"a":"core/part_of","v":["amazon/order_id",o]},
        {"e":["amazon/order_line",k],"a":"line/listing","v":["amazon/seller_sku",r['sku']]}]
write(f,'amazon/all_orders.txt',None,label='amazon orders+lines')
