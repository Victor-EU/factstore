from common import *
import pickle,collections as C
cust=pickle.load(open(os.environ['S']+'/cust.pkl','rb'))
def norm(e):
    u,_,dom=e.partition('@'); u=u.split('+')[0]
    if dom in('gmail.com','googlemail.com'): u=u.replace('.','')
    return u+'@'+dom
def groups(keyf):
    g=C.defaultdict(list)
    for i,d in cust.items(): g[keyf(d)].append(i)
    return [v for v in g.values() if len(v)>1]
order=lambda i:(cust[i]['first'],int(i.rsplit('/',1)[1]))
edges={}  # newer -> (older, rule)
for rule,conf,kf in [('mailbox',0.9,lambda d:norm(d['email'][0])),('name+address',0.7,lambda d:(d['name'][0],d['addr'][0][0],d['addr'][0][1]))]:
    n=0
    for g in groups(kf):
        g=sorted(g,key=order)
        for x in g[1:]:
            if x in edges: continue
            edges[x]=(g[0],rule,conf); n+=1
    print(rule,n)
# resolve chains: point at the root
def root(i):
    while i in edges: i=edges[i][0]
    return i
byrule=C.Counter(v[1] for v in edges.values()); print(byrule)
tgt=C.Counter(root(i) for i in edges); print('max dupes per survivor',max(tgt.values()), 'chains',sum(1 for i,v in edges.items() if v[0] in edges))
pickle.dump(edges,open(os.environ['S']+'/edges.pkl','wb'))
# write: per confidence
for conf in (0.9,0.7):
    f=[{"e":["shopify/customer_id",n.rsplit('/',1)[-1]],"a":"core/same_as","v":["shopify/customer_id",root(o).rsplit('/',1)[-1]]} for n,(o,r,c) in edges.items() if c==conf]
    if f and len(sys.argv)>1: write(f,'shopify/orders.jsonl',conf,label=f'same_as {conf}')
