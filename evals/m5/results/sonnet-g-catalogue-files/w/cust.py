import json,collections as C,re
P='exports/'
cu={}
for l in open(P+'shopify/orders.jsonl'):
    r=json.loads(l)
    if '/Order/' in r['id'] and r.get('customer'):
        c=r['customer']; d=cu.setdefault(c['id'],{'emails':set(),'names':set(),'addr':set(),'n':0,'first':r['createdAt'],'phone':set()})
        d['emails'].add((c['email'] or '').lower()); d['emails'].add((r['email'] or '').lower())
        d['names'].add(((c['firstName'] or '')+' '+(c['lastName'] or '')).strip().lower())
        sa=r.get('shippingAddress') or {}
        d['addr'].add(((sa.get('address1') or '').lower(),(sa.get('zip') or '')))
        d['phone'].add(c.get('phone')); d['n']+=1
        d['first']=min(d['first'],r['createdAt'])
print(len(cu),C.Counter(len(d['emails']) for d in cu.values()),C.Counter(len(d['names']) for d in cu.values()))
print(sum('' in d['emails'] for d in cu.values()))
def ne(e):
    u,_,dom=e.partition('@'); u=u.split('+')[0]
    if dom in('gmail.com','googlemail.com'): u=u.replace('.','')
    return u+'@'+dom
by=C.defaultdict(set)
for k,d in cu.items():
    for e in d['emails']:
        if e: by[ne(e)].add(k)
g=[v for v in by.values() if len(v)>1]
print('email groups',len(g),C.Counter(len(v) for v in g))
exact=C.defaultdict(set)
for k,d in cu.items():
    for e in d['emails']:
        if e: exact[e].add(k)
print('exact email groups',sum(len(v)>1 for v in exact.values()))
na=C.defaultdict(set)
for k,d in cu.items():
    for n in d['names']:
        for a in d['addr']:
            if n and a[0]: na[(n,a)].add(k)
print('name+addr groups',sum(len(v)>1 for v in na.values()))
import random
random.seed(1)
for v in random.sample([v for v in by.values() if len(v)>1],6):
    for k in v: print(k[-6:],cu[k]['emails'],cu[k]['names'],cu[k]['addr'],cu[k]['first'][:10])
    print()
print('nameaddr not email-same:')
n=0
for key,v in na.items():
    if len(v)>1:
        es=[{ne(e) for e in cu[k]['emails'] if e} for k in v]
        if not set.intersection(*es):
            n+=1
            if n<8:
                for k in v: print(k[-6:],cu[k]['emails'],cu[k]['names'],cu[k]['addr'],cu[k]['first'][:10])
                print()
print(n)
