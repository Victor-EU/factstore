from common import *
lim=int(sys.argv[1]) if len(sys.argv)>1 else None
V=variants(); v2c={v['id']:norm(v['sku']) for v in V}
cust=[];ords=[];lines=[];seen=set()
for l in open(P+'shopify/orders.jsonl'):
    r=json.loads(l)
    if '/Order/' in r['id']:
        if lim and len(ords)>=lim*3: continue
        oid=gid(r['id']); cid=gid(r['customer']['id'])
        if cid not in seen: seen.add(cid); cust.append({"e":["shopify/customer_id",cid],"a":"shopify/customer_id","v":cid})
        o=["shopify/order_id",oid]
        ords+=[{"e":o,"a":"shopify/order_id","v":oid},{"e":o,"a":"shopify/order_name","v":r['name']},{"e":o,"a":"order/customer","v":["shopify/customer_id",cid]}]
    elif '/LineItem/' in r['id']:
        if lim and len(ords)>=lim*3 and gid(r['__parentId']) not in {f['v'] for f in ords if f['a']=='shopify/order_id'}: continue
        li=["shopify/line_item_id",gid(r['id'])]
        lines+=[{"e":li,"a":"shopify/line_item_id","v":gid(r['id'])},{"e":li,"a":"core/part_of","v":["shopify/order_id",gid(r['__parentId'])]},{"e":li,"a":"line/sku","v":sku(v2c[r['variant']['id']])}]
S=['shopify/orders.jsonl']
write(cust,S,label='cust'); write(ords,S,label='orders'); write(lines,S,label='lines')
