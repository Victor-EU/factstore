from lib import *
import glob
pre={'MT':'NBBW','HT':'SZHT','LX':'YWLX','RF':'DGRF','MJ':'FSMJ','YD':'XMYD','QS':'NBQS','TY':'HZTY'}
ci=json.load(open(S+'ci.json'))
# vendor -> supplier code, by company name printed on that supplier's invoices
cname={}
for f,t in ci.items():
    m=re.search(r'\n([A-Z][A-Z ,\.&]+CO\., LTD\.)\n',t); cname[pre[f.split('_')[1][:2]]]=m.group(1).lower()
qb=list(csv.DictReader(open(EX+'quickbooks/vendors.csv')))
f=[];seen=set()
for v in qb:
    code=[c for c,n in cname.items() if n==v['Company name'].lower()]
    assert len(code)<=1
    if code: f.append({'e':['supplier/code',code[0]],'a':'quickbooks/vendor','v':v['Vendor']}); seen.add(code[0])
    else: f.append({'e':['quickbooks/vendor',v['Vendor']],'a':'quickbooks/vendor','v':v['Vendor']}); print('no supplier:',v['Vendor'])
assert seen==set(pre.values()),seen
write(f,'quickbooks/vendors.csv',1)
# factory crosswalk
prods=[json.loads(l) for l in open(EX+'shopify/products.jsonl')]
P={p['id']:p for p in prods if 'Product/' in p['id']}
title={}
for v in prods:
    if 'ProductVariant/' in v['id']:
        t=(P[v['__parentId']]['title']+' '+v['title']).lower().replace(',','')
        assert t not in title; title[t]=hubcode(v['sku'])
used={};tot=0
for fn,t in sorted(ci.items()):
    s=pre[fn.split('_')[1][:2]];L=t.split('\n');facts=[]
    for i,l in enumerate(L):
        m=re.match(r'^([A-Z]{2}-?\d{3,5}|\d{3}) (.*)',l)
        if m and i+2<len(L):
            h=re.match(r'^(\d{4}\.\d{2}\.\d{4})',L[i+2])
            if not h: continue
            d=m.group(2).lower().replace(',','')
            hub=title[d]; code=f'{s}:{m.group(1)}'
            assert used.setdefault(hub,(code,h.group(1)))==(code,h.group(1)),(hub,code)
            facts+=[{'e':['sku/code',hub],'a':'factory/item_code','v':code},
                    {'e':['sku/code',hub],'a':'sku/supplier','v':['supplier/code',s]},
                    {'e':['sku/code',hub],'a':'sku/hs_code','v':h.group(1)}]
    if facts: tot+=write(facts,'supplier_docs/'+fn,0.7)
print(len(used),len({v[0] for v in used.values()}))
