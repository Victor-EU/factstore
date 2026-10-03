import json,re,csv,sys
sys.path.insert(0,'.')
from items import items
X='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-s-kfe1uo8m/catalogue/work/exports/'
rows=[json.loads(l) for l in open(X+'shopify/products.jsonl')]
prod={r['id']:r for r in rows if 'sku' not in r}
var=[r for r in rows if 'sku' in r]
def toks(s): return set(re.findall(r'[a-z0-9]+',s.lower()))
cand=[]
for v in var:
    p=prod[v['__parentId']]
    cand.append((v,p['title']+' '+v['title']))
syn={'cream':'cream','white':'white'}
res={}
for k,d in items.items():
    desc=sorted(d['desc'])[0]
    dt=toks(desc)
    sc=sorted(((len(dt&toks(t))/len(dt|toks(t)),v['sku'],t) for v,t in cand),reverse=True)[:2]
    res[k]=(desc,sc)
    print(k,'|',desc,'|',sc[0][1],sc[0][2],round(sc[0][0],2),'| next',round(sc[1][0],2))
