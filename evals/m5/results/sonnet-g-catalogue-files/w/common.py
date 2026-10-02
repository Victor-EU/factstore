import json,csv,re,hashlib,collections as C,factstore,sys,os,time
P='exports/'
def sha(f): return hashlib.sha256(open(P+f,'rb').read()).hexdigest()
def doc(f): 
    h=sha(f); return h
def docfacts(files):
    out=[]
    for f in files:
        h=sha(f); out.append({"e":["document/hash",h],"a":"document/url","v":f})
    return out
def evid(files): return [{"e":"tmp:tx","a":"core/evidence","v":["document/hash",sha(f)]} for f in files]
def write(facts,files,conf=None,size=4000,label=''):
    """write facts in batches of whole-entity-agnostic chunks; each tx carries evidence"""
    tot=0;new=0
    for i in range(0,len(facts),size):
        chunk=facts[i:i+size]+docfacts(files)+evid(files)
        if conf is not None: chunk.append({"e":"tmp:tx","a":"core/confidence","v":str(conf)})
        r=factstore.transact(chunk)
        tot+=len(chunk)
    print(label,'facts',len(facts),'batches',(len(facts)+size-1)//size,flush=True)
    return r
def norm(s):
    s=s.upper().replace('_','-'); s=re.sub(r'-FBA$','',s)
    m=re.match(r'^AH-?([A-Z]{3})-?0*(\d+)-?([A-Z]{3})$',s)
    return f'AH-{m[1]}-{int(m[2]):04d}-{m[3]}' if m else None
def rd(f,**k): return list(csv.DictReader(open(P+f,encoding='utf-8-sig'),**k))
def gid(s): return s.rsplit('/',1)[1]
def variants():
    V=[json.loads(l) for l in open(P+'shopify/products.jsonl')]
    return [v for v in V if 'ProductVariant' in v['id']]
def sku(c): return ["sku/code",c]
