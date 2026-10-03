from common import *
S=os.environ['S']
d=json.load(open(S+'/pdftext.json'))
qb=list(csv.DictReader(open(EX+'/quickbooks/vendors.csv')))
codes={'NBBW','SZHT','YWLX','DGRF','FSMJ','XMYD','NBQS','HZTY'}
pref={'MT':'NBBW','HT':'SZHT','LX':'YWLX','RF':'DGRF','MJ':'FSMJ','YD':'XMYD','QS':'NBQS','TY':'HZTY'}
hdr={}
for f,t in d.items():
    if f.startswith('LCI'): continue
    p=re.match(r'(?:CI-PL_)?([A-Z]{2})',f)[1]; m=re.search(r'\n([A-Z][A-Z ,.\-&()]+CO\., LTD\.)\n',t); hdr[pref[p]]=m[1].lower()
f=[];other=[]
for r in qb:
    dom=r['Email'].split('@')[1].split('.')[0].upper()
    if dom in codes:
        assert r['Company name'].lower()==hdr[dom],(r,hdr[dom])
        f+= [{"e":["supplier/code",dom],"a":"supplier/code","v":dom},{"e":["supplier/code",dom],"a":"quickbooks/vendor","v":r['Vendor']}]
    else: other.append(r['Vendor'])
write(f,'quickbooks/vendors.csv',1,label='suppliers+qb')
write([{"e":["quickbooks/vendor",v],"a":"quickbooks/vendor","v":v} for v in other],'quickbooks/vendors.csv',None,label='non-supplier vendors '+str(other))
P=[json.loads(l) for l in open(EX+'/shopify/products.jsonl')]
par={p['id']:p for p in P if 'ProductVariant' not in p['id']}
tit={}
for p in P:
    if 'ProductVariant' in p['id']: tit[(par[p['__parentId']]['title']+' '+p['title']).lower()]=code_norm(p['sku'])
assert len(tit)==49
items={}
for fn,t in d.items():
    if fn.startswith('LCI'): continue
    s=pref[re.match(r'(?:CI-PL_)?([A-Z]{2})',fn)[1]]; L=t.split('\n')
    for i,l in enumerate(L):
        m=re.match(r'^([A-Z]{0,2}-?\d{3,4}) ([a-z0-9].*)$',l)
        if m and i+1<len(L) and re.search(r'[一-鿿]',L[i+1]):
            e=items.setdefault((s,m[1]),dict(desc=set(),hs={},)); e['desc'].add(m[2])
            h=re.match(r'^(\d{4}\.\d{2}\.\d{4}) ',L[i+2])
            if h: e['hs'].setdefault(h[1],fn)
assert len(items)==49
for (s,c),e in sorted(items.items()):
    assert len(e['desc'])==1 and len(e['hs'])==1
    sku=tit[next(iter(e['desc']))]; hs,doc=next(iter(e['hs'].items()))
    h=["sku/code",sku]
    write([{"e":h,"a":"factory/item_code","v":f"{s}:{c}"},{"e":h,"a":"sku/supplier","v":["supplier/code",s]},{"e":h,"a":"sku/hs_code","v":hs}],'supplier_docs/'+doc,0.7,label=f'{s}:{c}->{sku}')
