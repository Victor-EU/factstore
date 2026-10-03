from lib import *
o=[json.loads(l) for l in open(X+'shopify/orders.jsonl')]
hs,_=doc_facts('shopify/orders.jsonl')
orders=[x for x in o if '__parentId' not in x]
cust={};first={};addr=C.defaultdict(set)
for x in orders:
    c=x['customer'];i=gid(c['id']);cust.setdefault(i,c);first[i]=min(first.get(i,'z'),x['createdAt'])
    a=x['shippingAddress']
    if a and a['name'].strip().lower()==(c['firstName']+' '+c['lastName']).strip().lower():
        addr[i].add((a['name'].strip().lower(),a['address1'].strip().lower(),a['zip']))
def norm(e):
    l,d=e.strip().lower().split('@'); l=l.split('+')[0]
    if d in('gmail.com','googlemail.com'): l=l.replace('.','')
    return l+'@'+d
mb=C.defaultdict(set); na=C.defaultdict(set)
for i,c in cust.items(): mb[norm(c['email'])].add(i)
for i,s in addr.items():
    for k in s: na[k].add(i)
par={i:i for i in cust}
def find(x):
    while par[x]!=x: par[x]=par[par[x]]; x=par[x]
    return x
def comps(groups):
    global par
    par={i:i for i in cust}
    for g in groups:
        g=list(g)
        for y in g[1:]: par[find(y)]=find(g[0])
    r=C.defaultdict(set)
    for i in cust: r[find(i)].add(i)
    return {i:g for g in r.values() if len(g)>1 for i in g}
mbc=comps([g for g in mb.values() if len(g)>1])
allc=comps([g for g in list(mb.values())+list(na.values()) if len(g)>1])
groups={frozenset(g) for g in allc.values()}
print('groups',len(groups),C.Counter(len(g) for g in groups))
t9=[];t7=[]
pairs=[]
for g in groups:
    root=min(g,key=lambda i:(first[i],i))
    for i in g:
        if i==root: continue
        fact={"e":["shopify/customer_id",i],"a":"core/same_as","v":["shopify/customer_id",root]}
        (t9 if mbc.get(i) and root in mbc[i] else t7).append(fact)
        pairs.append((i,root,0.9 if fact in t9 else 0.7))
print(len(t9),len(t7))
json.dump(pairs,open('w/same_as.json','w'))
if '--write' in sys.argv if (sys:=__import__('sys')) else 0:
    print(write(t9,[hs],0.9)); print(write(t7,[hs],0.7))
