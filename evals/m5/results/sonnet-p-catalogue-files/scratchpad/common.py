import hashlib,json,csv,re,os,sys,collections as C,time
import factstore
W='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-p-v76cz30z/catalogue/work/exports/'
S='/private/tmp/claude-501/-private-var-folders-qj-j67my3-j6bzb4y5t82bvmkfh0000gn-T-m5-p-v76cz30z-catalogue-work/3729562d-84d8-4aa2-a3cf-5ed2509853ea/scratchpad/'
def doc(path):
    h=hashlib.sha256(open(W+path,'rb').read()).hexdigest()
    return ['document/hash',h]
def docfacts(path):
    d=doc(path)
    return [{"e":d,"a":"document/url","v":path},{"e":d,"a":"document/issued_at","v":"2026-10-03T00:00:00Z"}]
def tx(facts,paths,conf=None):
    paths=[paths] if isinstance(paths,str) else paths
    f=list(facts)
    for p in paths:
        f+=docfacts(p); f.append({"e":"tmp:tx","a":"core/evidence","v":doc(p)})
    if conf is not None: f.append({"e":"tmp:tx","a":"core/confidence","v":str(conf)})
    return factstore.transact(f)
def batched(facts_groups,paths,conf=None,size=2500):
    """facts_groups: list of lists of facts (one group per record, kept together)."""
    buf=[];n=0;t0=time.time()
    for g in facts_groups:
        buf+=g
        if len(buf)>=size:
            tx(buf,paths,conf); n+=len(buf); buf=[]
    if buf: tx(buf,paths,conf); n+=len(buf)
    print('wrote',n,'facts',round(time.time()-t0),'s',flush=True)
# ---- hubs
def products():
    prod={};vs=[]
    for l in open(W+'shopify/products.jsonl'):
        d=json.loads(l)
        if 'ProductVariant' in d['id']: vs.append(d)
        else: prod[d['id']]=d
    return prod,vs
HUBFIX={ # shopify spelling -> hub spelling (pattern AH-XXX-NNNN-CCC)
 'AH-CTB-16-LRG':'AH-CTB-0016-LRG','AHUTN0017NAT':'AH-UTN-0017-NAT','AH-TRY-18-NAT':'AH-TRY-0018-NAT',
 'ah-btl-0020-blk':'AH-BTL-0020-BLK','AH-JAR-22-STL':'AH-JAR-0022-STL','AH-TPT-23-CLR':'AH-TPT-0023-CLR'}
def hub(shopsku): return HUBFIX.get(shopsku,shopsku)
def gid(s): return s.split('/')[-1]
