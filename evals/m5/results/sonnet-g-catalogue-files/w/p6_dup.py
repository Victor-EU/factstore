from common import *
cu={}
for l in open(P+'shopify/orders.jsonl'):
    r=json.loads(l)
    if '/Order/' in r['id']:
        c=r['customer']; d=cu.setdefault(gid(c['id']),{'em':set(),'nm':set(),'ad':set(),'first':r['createdAt']})
        d['em'].add(c['email'].lower()); d['nm'].add((c['firstName']+' '+c['lastName']).strip().lower())
        sa=r['shippingAddress'] or {}; d['ad'].add(((sa.get('address1') or '').lower(),sa.get('zip') or ''))
        d['first']=min(d['first'],r['createdAt'])
def ne(e):
    u,_,dom=e.partition('@'); u=u.split('+')[0]
    if dom in('gmail.com','googlemail.com'): u=u.replace('.','')
    return u+'@'+dom
pairs={}  # (dup, orig) -> rule
def link(ks,rule):
    ks=sorted(ks,key=lambda k:(cu[k]['first'],k))
    for k in ks[1:]: pairs.setdefault(k,{}).setdefault(ks[0],rule)  # all point to oldest
by=C.defaultdict(set)
for k,d in cu.items():
    for e in d['em']: by[ne(e)].add(k)
skipped=[]
for e,ks in by.items():
    if len(ks)>1:
        if len({n for k in ks for n in cu[k]['nm']})>1: skipped.append(('email',e)); continue
        link(ks,'email')
na=C.defaultdict(set)
for k,d in cu.items():
    for n in d['nm']:
        for a in d['ad']:
            if n and a[0] and a[1]: na[(n,a)].add(k)
for key,ks in na.items():
    if len(ks)>1: link(ks,'nameaddr')
# resolve one target per dup: prefer email rule
final={}
for k,t in pairs.items():
    best=sorted(t.items(),key=lambda x:(x[1]!='email',cu[x[0]]['first']))[0]
    final[k]=best
# chains: target must itself be a root
for k in list(final):
    t,r=final[k]; seen={k}
    while t in final:
        assert t not in seen; seen.add(t); t2,r2=final[t]; t=t2; r='nameaddr' if 'nameaddr' in (r,r2) else 'email'
    final[k]=(t,r)
bad=[k for k,(t,_) in final.items() if t in final]
print('pairs',len(final),C.Counter(r for _,r in final.values()),'skipped',skipped,'chained',bad)
tgt=C.Counter(t for t,_ in final.values()); print('max inbound',tgt.most_common(3))
json.dump({k:[t,r] for k,(t,r) in final.items()},open('w/same_as.json','w'))
if '--write' in sys.argv:
    for rule,conf in (('email',0.9),('nameaddr',0.7)):
        fs=[{"e":["shopify/customer_id",k],"a":"core/same_as","v":["shopify/customer_id",t]} for k,(t,r) in final.items() if r==rule]
        write(fs,['shopify/orders.jsonl'],conf,label=rule)
