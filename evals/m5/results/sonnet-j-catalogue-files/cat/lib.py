import json,csv,re,hashlib,collections,os,sys,glob
import factstore
EX='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-j-vps9guuv/catalogue/work/exports/'
SCR=glob.glob('/private/tmp/claude-501/-private-var-folders-qj-j67my3-j6bzb4y5t82bvmkfh0000gn-T-m5-j-vps9guuv-catalogue-work/*/scratchpad')[0]
LIMIT=int(os.environ.get('LIMIT','0'))
def sha(p): return hashlib.sha256(open(EX+p,'rb').read()).hexdigest()
def write(facts,path,conf=None,chunk=4000,label=''):
    h=sha(path)
    pre=[{"e":["document/hash",h],"a":"document/url","v":path},{"e":"tmp:tx","a":"core/evidence","v":["document/hash",h]}]
    if conf is not None: pre.append({"e":"tmp:tx","a":"core/confidence","v":str(conf)})
    n=0
    for i in range(0,len(facts),chunk):
        r=factstore.transact(pre+facts[i:i+chunk]); n+=1
    print(label or path,len(facts),'facts',n,'tx',flush=True)
def f(e,a,v): return {"e":e,"a":a,"v":v}
def canon(sku):
    m=re.fullmatch(r'AH-?([A-Za-z]{3})-?(\d+)-?([A-Za-z]{3})',sku,re.I)
    return 'AH-%s-%04d-%s'%(m.group(1).upper(),int(m.group(2)),m.group(3).upper())
def shopify_variants():
    P=[json.loads(l) for l in open(EX+'shopify/products.jsonl')]
    return [p for p in P if 'sku' in p]
def gid(x): return x.rsplit('/',1)[1]
