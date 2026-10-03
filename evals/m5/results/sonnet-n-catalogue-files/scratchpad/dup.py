import json,collections as C,sys
exec(open('load.py').read().split("if STEP=='hubs'")[0].replace("STEP=sys.argv[1]","STEP=''"))
cust=C.defaultdict(lambda:{'em':set(),'ad':set(),'own':None,'first':'9'})
for l in open(EX+'shopify/orders.jsonl'):
    r=json.loads(l)
    if 'quantity' in r and 'sku' in r: continue
    c=r['customer'];i=gid(c['id']);d=cust[i]
    d['own']=((c['firstName'] or '')+' '+(c['lastName'] or '')).strip().lower()
    for e in (c.get('email'),r.get('email')):
        if e: d['em'].add(e.lower())
    d['first']=min(d['first'],r['createdAt'])
    a=r.get('shippingAddress')
    if a: d['ad'].add((a['name'].lower(),a['address1'].lower(),a['zip']))
def norm(e):
    u,dm=e.split('@');u=u.split('+')[0]
    if dm in('gmail.com','googlemail.com'): u=u.replace('.','');dm='gmail.com'
    return u+'@'+dm
mb=C.defaultdict(set);ad=C.defaultdict(set)
for i,d in cust.items():
    for e in d['em']: mb[norm(e)].add(i)
    for (n,a,z) in d['ad']:
        if n==d['own']: ad[(n,a,z)].add(i)
edges={}  # (newer,older)->conf
mism=0
def old(i): return (cust[i]['first'],int(i))
def add(group,conf,rule):
    global mism
    g=sorted(group,key=old)
    for n in g[1:]:
        edges.setdefault(n,[]).append((g[0],conf,rule))
for k,g in mb.items():
    if len(g)>1:
        if len({cust[i]['own'] for i in g})>1: mism+=1; print('own-name mismatch',k,[cust[i]['own'] for i in g])
        add(g,0.9,'mailbox')
for k,g in ad.items():
    if len(g)>1: add(g,0.7,'name+addr')
# union-find roots so same_as points at the oldest in each component
par={}
def find(x):
    while par.get(x,x)!=x: x=par[x]
    return x
for n,es in edges.items():
    for o,_,_ in es:
        a,b=find(n),find(o)
        if a!=b:
            if old(a)<old(b): par[b]=a
            else: par[a]=b
root={n:find(n) for n in edges}
inbound=C.Counter(root.values())
print('dups',len(edges),'roots',len(inbound),'max inbound',max(inbound.values()),C.Counter(inbound.values()))
rules=C.Counter()
out=C.defaultdict(list)
for n,r in root.items():
    es=edges[n]; direct=[e for e in es if e[0]==r]
    conf=max(e[1] for e in direct) if direct else min(e[1] for e in es)
    rule=[e[2] for e in direct if e[1]==conf][0] if direct else 'chain'
    rules[(rule,conf)]+=1; out[conf].append((n,r))
print(rules)
json.dump({str(k):v for k,v in out.items()},open('same_as.json','w'))
if len(sys.argv)>1 and sys.argv[1]=='write':
    for conf,prs in out.items():
        write([F(["shopify/customer_id",n],"core/same_as",["shopify/customer_id",r]) for n,r in prs],'shopify/orders.jsonl',conf)
import random
random.seed(1)
for conf in out:
    print('== conf',conf)
    for n,r in random.sample(out[conf],10):
        print([ (sorted(cust[x]['em']),cust[x]['own'],sorted(cust[x]['ad'])[:1]) for x in (n,r)])
