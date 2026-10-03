import json,re,collections as C,pickle
cust={}
for l in open('shopify/orders.jsonl'):
    if '/Order/' not in l[:40]: continue
    o=json.loads(l); c=o['customer']; a=o.get('shippingAddress') or {}
    d=cust.setdefault(c['id'],dict(email=set(),name=set(),addr=set(),first=o['createdAt'],phone=set()))
    d['email'].add((c['email'] or '').lower()); d['name'].add(((c['firstName'] or '')+' '+(c['lastName'] or '')).lower().strip())
    d['addr'].add((a.get('address1','').lower(),a.get('zip',''))); d['phone'].add(c.get('phone'))
    d['first']=min(d['first'],o['createdAt'])
def norm(e):
    u,_,dom=e.partition('@'); u=u.split('+')[0]
    if dom in('gmail.com','googlemail.com'): u=u.replace('.','')
    return u+'@'+dom
print(len(cust), C.Counter(len(d['email']) for d in cust.values()), sum(1 for d in cust.values() if '' in d['email']))
raw=C.defaultdict(list); nm=C.defaultdict(list); na=C.defaultdict(list)
for i,d in cust.items():
    e=next(iter(d['email'])); raw[e].append(i); nm[norm(e)].append(i)
    na[(next(iter(d['name'])),next(iter(d['addr'])))].append(i)
print('same raw email groups',sum(1 for v in raw.values() if len(v)>1))
g=[v for v in nm.values() if len(v)>1]; print('norm groups',len(g),C.Counter(len(v) for v in g))
g2=[v for v in na.values() if len(v)>1]; print('name+addr groups',len(g2),C.Counter(len(v) for v in g2))
import itertools
shown=0
for v in g:
    if all(len({next(iter(cust[i]['email'])) for i in v})>0 for _ in [0]) and len({next(iter(cust[i]['email'])) for i in v})>1 and shown<12:
        shown+=1; print([ (i[-6:],next(iter(cust[i]['email'])),next(iter(cust[i]['name'])),next(iter(cust[i]['addr']))) for i in v])
print('--- name+addr')
for v in g2[:8]: print([ (i[-6:],next(iter(cust[i]['email'])),next(iter(cust[i]['name'])),next(iter(cust[i]['addr']))) for i in v])
pickle.dump({i:{k:(sorted(x) if isinstance(x,set) else x) for k,x in d.items()} for i,d in cust.items()},open(__import__('os').environ['S']+'/cust.pkl','wb'))
