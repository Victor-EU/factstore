from common import *
import pickle
acc=pickle.load(open(S+'acc.pkl','rb')); own=pickle.load(open(S+'own.pkl','rb'))
def norm(e):
    u,d=e.split('@'); u=u.split('+')[0]
    if d in('gmail.com','googlemail.com'): u=u.replace('.',''); d='gmail.com'
    return u+'@'+d
by=C.defaultdict(set); ad=C.defaultdict(set)
for k,a in acc.items():
    for e in a['emails']: by[norm(e)].add(k)
    for x in a['addr']:
        if x[0]==own[k]: ad[x].add(k)
key=lambda k:(acc[k]['first'],k)
link={}  # newer -> (older, tier)
def add(group,tier):
    g=sorted(group,key=key)
    for n in g[1:]:
        if n not in link or tier>link[n][1]: link[n]=(g[0],tier)
for v in ad.values():
    if len(v)>1: add(v,0.7)
for v in by.values():
    if len(v)>1: add(v,0.9)
print(len(link),C.Counter(t for _,t in link.values()))
pickle.dump(link,open(S+'link.pkl','wb'))
for t in (0.9,0.7):
    f=[{"e":["shopify/customer_id",n],"a":"core/same_as","v":["shopify/customer_id",o]} for n,(o,tt) in link.items() if tt==t]
    tx(f,'shopify/orders.jsonl',t)
