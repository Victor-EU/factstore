from lib import *
vmap=json.load(open(S+'vmap.json'))
rows=[json.loads(l) for l in open(EX+'shopify/orders.jsonl')]
ids=lambda g:g.split('/')[-1]
facts=[];first={}
for r in rows:
    if '__parentId' in r:
        li=ids(r['id']);o=ids(r['__parentId'])
        facts+= [{'e':['shopify/line_item_id',li],'a':'core/part_of','v':['shopify/order_id',o]},
                 {'e':['shopify/line_item_id',li],'a':'line/sku','v':['sku/code',vmap[ids(r['variant']['id'])]]}]
    else:
        o=ids(r['id']);c=ids(r['customer']['id'])
        first[c]=min(first.get(c,'9'),r['createdAt'])
        facts+= [{'e':['shopify/order_id',o],'a':'shopify/order_name','v':r['name']},
                 {'e':['shopify/order_id',o],'a':'order/customer','v':['shopify/customer_id',c]}]
n=int(sys.argv[1]) if len(sys.argv)>1 else None
if n: facts=facts[:n]
print(len(facts))
write(facts,'shopify/orders.jsonl')
# duplicates
if not n:
    P=json.load(open(S+'pairs.json'))
    par={}
    # union-find; survivor = earliest first order
    uf={}
    def f(x):
        while uf.get(x,x)!=x: x=uf[x]
        return x
    conf={}
    for rule,k in (('A',0.9),('B',0.7)):
        for a,b in P[rule]:
            uf.setdefault(a,a);uf.setdefault(b,b)
            ra,rb=f(a),f(b)
            if ra!=rb:
                s,d=sorted([ra,rb],key=lambda i:(first[i],i)); uf[d]=s
    # every non-survivor points at survivor; confidence per its direct evidence
    ev={}
    for rule,k in (('B',0.7),('A',0.9)):
        for a,b in P[rule]:
            for x in(a,b): ev[x]=k
    groups=C.defaultdict(list)
    for x in uf: groups[f(x)].append(x)
    byconf=C.defaultdict(list)
    for s,g in groups.items():
        for x in g:
            if x!=s: byconf[ev[x]].append({'e':['shopify/customer_id',x],'a':'core/same_as','v':['shopify/customer_id',s]})
    print({k:len(v) for k,v in byconf.items()}, C.Counter(len(g) for g in groups.values()))
    for k,v in byconf.items(): write(v,'shopify/orders.jsonl',k)
