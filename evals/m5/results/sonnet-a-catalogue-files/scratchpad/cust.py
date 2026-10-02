import json,collections,re
from common import EX
O={};cu={}
first={}
for l in open(EX+'shopify/orders.jsonl'):
    d=json.loads(l)
    if '__parentId' in d: continue
    O[d['id']]=d; c=d['customer']; cid=c['id']
    cu.setdefault(cid,{'email':c['email'],'fn':c['firstName'],'ln':c['lastName'],'addr':set()})
    a=d['shippingAddress']
    if a: cu[cid]['addr'].add((a['address1'],a['zip']))
    first[cid]=min(first.get(cid,'9'),d['createdAt'])
def norm(e):
    u,d=e.lower().split('@'); u=u.split('+')[0]
    if d in('gmail.com','googlemail.com'): u=u.replace('.','')
    return u+'@'+d
g=collections.defaultdict(set)
for k,c in cu.items(): g[('mail',norm(c['email']))].add(k)
n=collections.defaultdict(set)
for k,c in cu.items():
    for a in c['addr']: n[(c['fn'].lower(),c['ln'].lower(),a[0].lower(),a[1])].add(k)
exact=collections.defaultdict(set)
for k,c in cu.items(): exact[c['email'].lower()].add(k)
pairs={}  # dup -> (survivor, tier)
def link(grp,tier):
    ids=sorted(grp,key=lambda i:(first[i],int(i.rsplit('/',1)[1])))
    for d in ids[1:]:
        if d not in pairs: pairs[d]=(ids[0],tier)
for k,v in exact.items():
    if len(v)>1: link(v,1)
for k,v in g.items():
    if len(v)>1: link(v,0.9)
mail_n=len(pairs)
for k,v in n.items():
    if len(v)>1: link(v,0.7)
print(len(cu),len(pairs),mail_n,collections.Counter(t for _,t in pairs.values()))
# sanity: chains
print('chains',sum(1 for s,_ in pairs.values() if s in pairs))
# name-addr only: print samples
ex=[(d,s) for d,(s,t) in pairs.items() if t==0.7][:5]
for d,s in ex: print(cu[d]['email'],cu[s]['email'],cu[d]['fn'],cu[d]['ln'])
