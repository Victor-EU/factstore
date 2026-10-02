import json,csv,re,hashlib,collections,sys,os
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import factstore, factory
X='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m4-catalogue-v23fb7l9/work/exports/'
DRY='--dry' in sys.argv
def sha(p): return hashlib.sha256(open(X+p,'rb').read()).hexdigest()
def tx(facts, doc, conf=None, n=4000):
    """write facts in chunks, each pointing at the document; returns count"""
    h=sha(doc); tot=0
    for i in range(0,len(facts),n):
        ch=facts[i:i+n]
        pre=[{"e":["document/hash",h],"a":"document/url","v":doc},
             {"e":"tmp:tx","a":"core/evidence","v":["document/hash",h]}]
        if conf is not None: pre.append({"e":"tmp:tx","a":"core/confidence","v":str(conf)})
        if DRY: tot+=len(ch); continue
        r=factstore.transact(pre+ch); tot+=len(ch)
        print(doc,conf,i,'tx',r.tx if hasattr(r,'tx') else r['tx'],'unchanged',len(r.unchanged if hasattr(r,'unchanged') else r['unchanged']))
    return tot
def canon(s):
    s=s.upper().strip()
    m=re.match(r'^AH-?([A-Z]{3})-?0*(\d+)-?([A-Z]{3})(?:-FBA)?$',s)
    assert m,s
    return f'AH-{m.group(1)}-{int(m.group(2)):04d}-{m.group(3)}'
def read_shopify_products():
    vs=[json.loads(l) for l in open(X+'shopify/products.jsonl')]
    return [v for v in vs if 'ProductVariant' in v['id']]
def gid(s): return s.rsplit('/',1)[1]
