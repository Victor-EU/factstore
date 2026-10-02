from common import *
import sys
live = len(sys.argv)>1 and sys.argv[1]=='live'
parents,vs=load_products()
qb=list(csv.DictReader(open(X+'/quickbooks/vendors.csv')))
byco={r['Company name'].upper().replace('.',''):r['Vendor'] for r in qb}
sup={}   # code -> (english name, set of docs)
items={}
for f in sorted(glob.glob(S+'/txt/*.txt')):
    b=os.path.basename(f)
    if b.startswith('LCI'): continue
    t=open(f).read(); em=re.search(r'Email: \S+@(\w+)\.example',t); s=em.group(1).upper()
    L=t.split('\n'); name=L[1].strip()
    d=sup.setdefault(s,[name,set()]); assert d[0]==name,(s,d[0],name); d[1].add(b[:-4]+'.pdf')
    for i,l in enumerate(L):
        if i+2<len(L) and re.match(r'^\d{4}\.\d{2}\.\d{4} ',L[i+2]) and re.match(r'^\S+ [a-z]',l):
            it,dd=l.split(' ',1); k=(s,it)
            v=(norm_desc(dd),L[i+2].split()[0]); assert items.setdefault(k,v)==v
            d[1].add(b[:-4]+'.pdf')
print({k:(v[0],len(v[1])) for k,v in sup.items()})
S1=[];unm=[]
for code,(name,docs) in sup.items():
    q=byco.get(name.upper().replace('.',''))
    e=["supplier/code",code]
    S1+=[{"e":e,"a":"supplier/code","v":code},{"e":e,"a":"supplier/name","v":{r['Vendor']:r['Company name'] for r in qb}[q] if q else name}]
    if q: S1.append({"e":e,"a":"quickbooks/vendor","v":q})
    else: unm.append(code)
print('supplier w/o QB vendor',unm)
matched={byco[n[0].upper().replace('.','')] for n in sup.values() if n[0].upper().replace('.','') in byco}
others=[r['Vendor'] for r in qb if r['Vendor'] not in matched]; print('QB non-supplier vendors',others)
O=[{"e":["quickbooks/vendor",v],"a":"quickbooks/vendor","v":v} for v in others]
skdesc={}
for v in vs:
    p=parents[v['__parentId']]; skdesc[norm_desc(p['title']+' '+v['title'])]=canon(v['sku'])
E=[];used={}
for (s,it),(d,hs) in sorted(items.items()):
    c=skdesc[d]; assert c not in used,(c,used.get(c),s,it); used[c]=(s,it)
    e=["sku/code",c]
    E+=[{"e":e,"a":"factory/item_code","v":f"{s}:{it}"},{"e":e,"a":"sku/supplier","v":["supplier/code",s]},{"e":e,"a":"sku/hs_code","v":hs}]
assert len(used)==49
print(len(E)//3)
pdfs=sorted({X+'/supplier_docs/'+x for v in sup.values() for x in v[1]})
if live:
    write(S1,[X+'/quickbooks/vendors.csv']+pdfs,0.9,label='suppliers')
    write(O,[X+'/quickbooks/vendors.csv'],1,label='qb other vendors')
    write(E,pdfs,0.7,label='supply side')
