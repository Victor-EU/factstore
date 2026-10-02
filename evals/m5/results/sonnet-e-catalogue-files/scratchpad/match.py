import json,re,collections,subprocess,sys
exec(open('parse_docs.py').read().split("print(len(items)")[0])
W='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-e-o67pidv7/catalogue/work/exports/'
prods={};vars_=[]
for l in open(W+'shopify/products.jsonl'):
    d=json.loads(l)
    (vars_ if 'sku' in d else prods.__setitem__(d['id'],d) if False else vars_).append(d) if 'sku' in d else prods.__setitem__(d['id'],d)
def norm(s):
    s=s.lower().replace(',','').replace('(','').replace(')','')
    return re.sub(r'\s+',' ',s).strip()
cands={}
for v in vars_:
    p=prods[v['__parentId']]
    cands[v['sku']]=norm(p['title']+' '+v['title'])
for k,v in sorted(items.items()):
    d=norm(list(v['desc'])[0])
    best=sorted(cands.items(), key=lambda kv:-len(set(kv[1].split())&set(d.split()))/len(set(kv[1].split())|set(d.split())))[:2]
    print(k,'|',d,'=>',best[0],'|',best[1][0])
