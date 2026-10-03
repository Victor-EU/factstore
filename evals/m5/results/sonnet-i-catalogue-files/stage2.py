from lib import *
exec(open('parse_docs.py').read())
H=json.load(open('w/hubs.json'))['hubs']
# hs
for f,t in d.items():
    m=re.search(r'sales@(\w+)\.example',t)
    if not m: continue
    s=m.group(1).upper();L=t.split('\n')
    for i,l in enumerate(L):
        if i>=2 and re.search(r'[一-鿿]',L[i-1]) and not re.search(r'[一-鿿]',L[i-2]):
            h=re.match(r'^(\d{4}\.\d{2}\.\d{4}) ',l); m2=re.match(r'^(\S+) ',L[i-2])
            if h and m2: items[(s,m2.group(1))]['hs'].add(h.group(1))
# our titles
prods=[json.loads(l) for l in open(X+'shopify/products.jsonl')]
P={p['id']:p for p in prods if 'sku' not in p}
bydesc={}
for p in prods:
    if 'sku' in p:
        k=(P[p['__parentId']]['title']+' '+p['title']).lower(); assert k not in bydesc; bydesc[k]=gid(p['id'])
pdfs=sorted({f for v in items.values() for f in v['docs']})
dh=[]; df=[]
for f in pdfs:
    h,x=doc_facts('supplier_docs/'+f); dh.append(h); df+=x
write(df,[])
f=[];used=set()
for (s,code),v in sorted(items.items()):
    (desc,)=v['desc']; vid=bydesc[desc]; assert vid not in used; used.add(vid)
    e=["shopify/variant_id",vid]
    f+=[{"e":e,"a":"factory/item_code","v":f"{s}:{code}"},{"e":e,"a":"sku/supplier","v":["supplier/code",s]}]
    (hs,)=v['hs']; f.append({"e":e,"a":"sku/hs_code","v":hs})
print(len(used)); print(write(f,dh,0.7))
# quickbooks vendors <-> suppliers, by email domain; name equal to legal name printed on the docs
vend=list(csv.DictReader(open(X+'quickbooks/vendors.csv')))
hq,hqf=doc_facts('quickbooks/vendors.csv'); write(hqf,[])
f=[];plain=[]
legal={}
for fn,t in d.items():
    m=re.search(r'sales@(\w+)\.example',t); n=re.search(r'\n([A-Z][A-Z ,\.&]+CO\., LTD\.)\n',t)
    if m and n: legal[m.group(1).upper()]=n.group(1)
print(legal)
for r in vend:
    m=re.match(r'sales@(\w+)\.example',r['Email'])
    if m and m.group(1).upper() in legal:
        s=m.group(1).upper(); assert legal[s].lower()==r['Company name'].lower(),(s,legal[s],r['Company name'])
        f.append({"e":["supplier/code",s],"a":"quickbooks/vendor","v":r['Vendor']})
    else: plain.append({"e":["quickbooks/vendor",r['Vendor']],"a":"quickbooks/vendor","v":r['Vendor']})
print(len(f),len(plain),write(f,[hq]+dh[:0],0.9))
print(write(plain,[hq],1))
