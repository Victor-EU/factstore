from common import *
import pypdf,glob
qb=rd('quickbooks/vendors.csv')
code={}
for r in qb:
    m=re.match(r'sales@([a-z]+)\.example',r['Email'])
    if m: code[r['Vendor']]=m[1].upper()
print(code)
byco={r['Company name'].upper():code[r['Vendor']] for r in qb if r['Vendor'] in code}
facts_sup=[];facts_qb=[]
for r in qb:
    v=r['Vendor']
    if v in code: facts_sup+=[{"e":["supplier/code",code[v]],"a":"quickbooks/vendor","v":v}]
    else: facts_qb+=[{"e":["quickbooks/vendor",v],"a":"quickbooks/vendor","v":v}]
write(facts_sup,['quickbooks/vendors.csv'],0.9,label='qb suppliers')
write(facts_qb,['quickbooks/vendors.csv'],label='qb others')
# factory crosswalk
V=variants()
title={}
Pp={}
for l in open(P+'shopify/products.jsonl'):
    r=json.loads(l)
    if '/Product/' in r['id']: Pp[r['id']]=r['title']
for v in V: title[(Pp[v['__parentId']]+' '+v['title']).lower()]=norm(v['sku'])
items={};files=set();unm=set()
for f in sorted(glob.glob(P+'supplier_docs/CI-PL*.pdf')):
    t=pypdf.PdfReader(f).pages[0].extract_text(); L=t.split('\n')
    sup=next(byco[x] for x in byco if x.replace(',','') in t.upper().replace(',','') or x in t.upper())
    for i,l in enumerate(L):
        m=re.match(r'^(\S+) ([a-z0-9][a-z0-9 ,.-]+)$',l)
        if m and i+2<len(L):
            h=re.match(r'^(\d{4}\.\d{2}\.\d{4}) ',L[i+2])
            if h:
                k=(sup,m[1]); d=m[2]
                if d not in title: unm.add((k,d)); continue
                items.setdefault(k,set()).add((d,h[1],title[d])); files.add(f[len(P):])
print('unmatched',unm)
bad={k:v for k,v in items.items() if len(v)>1}; print('conflicts',bad)
by={}
for (s,ic),v in items.items():
    (d,hs,c),=v; by.setdefault(c,[]).append((s,ic,hs))
print(len(items),len(by),'multi',{c:v for c,v in by.items() if len(v)>1})
print('hubs without factory',sorted(set(norm(v['sku']) for v in V)-set(by)))
fa=[]
for c,[(s,ic,hs)] in by.items():
    fa+=[{"e":sku(c),"a":"factory/item_code","v":f"{s}:{ic}"},{"e":sku(c),"a":"sku/hs_code","v":hs},{"e":sku(c),"a":"sku/supplier","v":["supplier/code",s]}]
json.dump(fa,open('w/factory_facts.json','w'))
write(fa,sorted(files),0.7,label='factory')
