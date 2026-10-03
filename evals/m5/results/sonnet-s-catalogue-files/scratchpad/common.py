import hashlib,os,re,json,csv,sys,datetime,factstore
X='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-s-kfe1uo8m/catalogue/work/exports/'
_h={}
def doc(rel):
    """document facts + ref for an export file"""
    if rel not in _h:
        b=open(X+rel,'rb').read(); h=hashlib.sha256(b).hexdigest()
        ts=datetime.datetime.fromtimestamp(os.path.getmtime(X+rel),datetime.timezone.utc).strftime('%Y-%m-%dT00:00:00Z')
        _h[rel]=(h,ts)
    return _h[rel]
def docfacts(rels):
    f=[]
    for rel in rels:
        h,ts=doc(rel); e=['document/hash',h]
        f+= [{'e':e,'a':'document/url','v':rel},{'e':e,'a':'document/issued_at','v':ts},{'e':'tmp:tx','a':'core/evidence','v':e}]
    return f
def write(facts,rels,conf=None,chunk=3000,label=''):
    """facts: list; chunked by entity-agnostic size; each chunk carries evidence."""
    extra=docfacts(rels)
    if conf is not None: extra.append({'e':'tmp:tx','a':'core/confidence','v':str(conf)})
    n=0;tx=0
    for i in range(0,max(len(facts),1),chunk):
        part=facts[i:i+chunk]
        if not part: break
        r=factstore.transact(part+extra); tx+=1; n+=len(part)
    print(label,'facts',n,'tx',tx,flush=True)
HUB_RE=re.compile(r'^AH-[A-Z]{3}-\d{4}-[A-Z]{3}$')
def hubcode(s):
    if HUB_RE.match(s): return s
    m=re.match(r'^(AH)-?([A-Za-z]{3})-?(\d+)-?([A-Za-z]{3})$',s,re.I)
    return f'AH-{m.group(2).upper()}-{int(m.group(3)):04d}-{m.group(4).upper()}'
def lines(rel): return list(csv.DictReader(open(X+rel)))
def shopify_products():
    rows=[json.loads(l) for l in open(X+'shopify/products.jsonl')]
    return [r for r in rows if 'sku' in r]
