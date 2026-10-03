from common import *
lo,hi=int(sys.argv[1]),int(sys.argv[2])   # slice of shopify order records
prod,vs=products()
v2h={gid(v['id']):hub(v['sku']) for v in vs}
orders=[];lines=C.defaultdict(list)
for l in open(W+'shopify/orders.jsonl'):
    d=json.loads(l)
    if '__parentId' in d: lines[gid(d['__parentId'])].append(d)
    else: orders.append(d)
orders=orders[lo:hi]
def groups():
    for o in orders:
        oid=gid(o['id']); oe=["shopify/order_id",oid]
        g=[{"e":oe,"a":"shopify/order_name","v":o['name']},
           {"e":oe,"a":"order/customer","v":["shopify/customer_id",gid(o['customer']['id'])]}]
        for li in lines.get(oid,[]):
            le=["shopify/line_item_id",gid(li['id'])]
            g+=[{"e":le,"a":"core/part_of","v":oe},{"e":le,"a":"line/sku","v":["sku/code",v2h[gid(li['variant']['id'])]]}]
            assert hub(li['sku'])==v2h[gid(li['variant']['id'])]
        yield g
batched(groups(),'shopify/orders.jsonl',size=4000)
