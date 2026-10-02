import json,csv,re,hashlib,collections,glob,os,sys
import factstore
EX='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-e-o67pidv7/catalogue/work/exports/'
def sha(path): return hashlib.sha256(open(EX+path,'rb').read()).hexdigest()
def docfacts(paths):
    f=[]
    for p in paths:
        h=sha(p)
        f.append({'e':['document/hash',h],'a':'document/url','v':p})
    return f
def evid(paths,conf=None):
    f=docfacts(paths)
    for p in paths: f.append({'e':'tmp:tx','a':'core/evidence','v':['document/hash',sha(p)]})
    if conf is not None: f.append({'e':'tmp:tx','a':'core/confidence','v':str(conf)})
    return f
def write(facts,paths,conf=None,chunk=4000,dry=False):
    """facts split in chunks, each tx carries evidence"""
    n=0
    for i in range(0,len(facts),chunk):
        batch=facts[i:i+chunk]+evid(paths,conf)
        if dry: n+=len(batch);continue
        r=factstore.transact(batch)
        n+=len(batch)
    return n
def gid(s): return s.rsplit('/',1)[1]
# hub tables
def shopify_products():
    prods={};vars_=[]
    for l in open(EX+'shopify/products.jsonl'):
        d=json.loads(l)
        if 'sku' in d: vars_.append(d)
        else: prods[d['id']]=d
    return prods,vars_
def hub_code(s):
    """normalize a Shopify/other spelling to the house pattern AH-XXX-NNNN-CCC"""
    s=s.upper()
    if s.endswith('-FBA'): s=s[:-4]
    m=re.fullmatch(r'AH-?([A-Z]{3})-?(\d{1,4})-?([A-Z]{3})',s)
    return f'AH-{m.group(1)}-{int(m.group(2)):04d}-{m.group(3)}'
