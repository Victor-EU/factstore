from common import *
inv=list(csv.DictReader(open(P+'amazon/fba_inventory.txt'),delimiter='\t'))
ao=list(csv.DictReader(open(P+'amazon/all_orders.txt'),delimiter='\t'))
hubs={r[0] for r in factstore.query('select v from "sku/code"').rows}
asin={}
for r in ao:
    asin.setdefault(r['sku'],set()).add(r['asin'])
ex=[];nm=[]
seen=set()
for r in inv:
    c=norm(r['sku']); assert c in hubs and c not in seen; seen.add(c)
    assert asin[r['sku']]=={r['asin']},r
    g=ex if c==r['sku'] else nm
    g+= [{"e":sku(c),"a":"amazon/seller_sku","v":r['sku']},{"e":sku(c),"a":"amazon/asin","v":r['asin']},{"e":sku(c),"a":"amazon/fnsku","v":r['fnsku']}]
assert set(asin)=={r['sku'] for r in inv}
S=['amazon/fba_inventory.txt','amazon/all_orders.txt']
write(ex,S,1,label='amz exact'); write(nm,S,0.9,label='amz norm')
fb=rd('amazon/fba_inbound_shipments.csv')
write([{"e":["amazon/fba_shipment_id",r['Shipment ID']],"a":"amazon/fba_shipment_id","v":r['Shipment ID']} for r in fb],['amazon/fba_inbound_shipments.csv'],label='fba')
