import json,re,csv,glob,hashlib,collections as C,os
X='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-k-mid97be7/catalogue/work/exports/'
def sha(p): return hashlib.sha256(open(X+p,'rb').read()).hexdigest()
def clean_sku(s):
    s=s.upper()
    m=re.fullmatch(r'AH-?([A-Z]{3})-?(\d{1,4})-?([A-Z]{3})',s)
    if not m: return None
    return f'AH-{m[1]}-{int(m[2]):04d}-{m[3]}'
def norm(s): return re.sub(r'[^a-z0-9]','',s.lower())
def products():
    P=[json.loads(l) for l in open(X+'shopify/products.jsonl')]
    prod={p['id']:p for p in P if '/Product/' in p['id']}
    out=[]
    for v in P:
        if 'ProductVariant' in v['id']:
            p=prod[v['__parentId']]
            out.append(dict(vid=v['id'].split('/')[-1],sku=v['sku'],hub=clean_sku(v['sku']),upc=v['barcode'],name=p['title']+' '+v['title']))
    return out
def pdf_items():
    from pypdf import PdfReader
    res=[]
    for f in sorted(glob.glob(X+'supplier_docs/CI-PL*.pdf')):
        t='\n'.join(p.extract_text() for p in PdfReader(f).pages)
        em=re.search(r'Email: *\S+@(\w+)\.example',t)
        L=t.split('\n')
        for i,l in enumerate(L):
            if re.match(r'^\d{4}\.\d{2}\.\d{4} ',l) and i>=2:
                m=re.match(r'^(\S+) (.+)$',L[i-2])
                res.append((os.path.relpath(f,X),em.group(1).upper(),m[1],m[2],l.split()[0]))
    return res
