import json,csv,re,glob,hashlib,collections,os
X='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m4-catalogue-m_8_4617/work/exports'
S='/private/tmp/claude-501/-private-var-folders-qj-j67my3-j6bzb4y5t82bvmkfh0000gn-T-m4-catalogue-m-8-4617-work/de8e53a9-ae7b-4267-8509-f9ecfcf62c41/scratchpad'
def sha(p): return hashlib.sha256(open(p,'rb').read()).hexdigest()
def load_products():
    parents={};vs=[]
    for l in open(X+'/shopify/products.jsonl'):
        d=json.loads(l)
        if 'sku' in d: vs.append(d)
        else: parents[d['id']]=d
    return parents,vs
def canon(s):
    m=re.match(r'^AH([A-Z]{3})(\d+)([A-Z]{3})$',re.sub(r'[^A-Za-z0-9]','',s).upper())
    return 'AH-%s-%04d-%s'%(m.group(1),int(m.group(2)),m.group(3))
def num(gid): return gid.rsplit('/',1)[1]
def norm_desc(s):
    s=s.lower().replace(',',' ')
    return ' '.join(s.split())
import factstore
def rel(p): return os.path.relpath(p,X)
def write(facts,docs,conf=None,chunk=4000,label=''):
    """facts: list of dicts; docs: list of file paths (absolute) read. One tx per chunk; each carries evidence (+ confidence)."""
    hs=[(rel(p),sha(p)) for p in docs]
    pre=[]
    for u,h in hs: pre.append({"e":["document/hash",h],"a":"document/url","v":u})
    # group facts by entity key so an entity's facts stay together
    out=[];n=0
    def flush(buf):
        nonlocal n
        f=list(pre)+buf+[{"e":"tmp:tx","a":"core/evidence","v":["document/hash",h]} for u,h in hs]
        if conf is not None: f.append({"e":"tmp:tx","a":"core/confidence","v":str(conf)})
        r=factstore.transact(f); n+=1; return r
    buf=[]
    for f in facts:
        buf.append(f)
        if len(buf)>=chunk: flush(buf); buf=[]
    if buf: flush(buf)
    print(label,'facts',len(facts),'txs',n,flush=True)
