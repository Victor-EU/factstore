from common import *
import time
lo=int(sys.argv[1]) if len(sys.argv)>1 else 0
hi=int(sys.argv[2]) if len(sys.argv)>2 else 10**9
vmap={}
for v in shopify_products(): vmap[v['id'].split('/')[-1]]=hubcode(v['sku'])
sid=lambda s:s.split('/')[-1]
facts=[];n=0
bad=set()
t=time.time()
for l in open(X+'shopify/orders.jsonl'):
    d=json.loads(l)
    if '__parentId' in d:
        oid=sid(d['__parentId']); lid=sid(d['id']); var=sid(d['variant']['id']) if d.get('variant') else None
        if var not in vmap: bad.add((lid,var)); continue
        e=['shopify/line_item_id',lid]
        facts+=[{'e':e,'a':'core/part_of','v':['shopify/order_id',oid]},{'e':e,'a':'line/sku','v':['sku/code',vmap[var]]}]
    else:
        n+=1
        if not (lo<=n-1<hi): pass
        e=['shopify/order_id',sid(d['id'])]
        facts+=[{'e':e,'a':'shopify/order_name','v':d['name']},{'e':e,'a':'order/customer','v':['shopify/customer_id',sid(d['customer']['id'])]}]
print('orders',n,'facts',len(facts),'bad',len(bad),list(bad)[:3])
import pickle; pickle.dump(facts,open('shopify_facts.pkl','wb'))
