from lib import *
import sys
sys.path.insert(0,SCR)
exec(open(SCR+'/parse.py').read().split('for k,v in sorted')[0].replace("glob.glob('txt/","glob.glob(SCR+'/txt/"))
from lib import f
V=shopify_variants();P={}
for l in open(EX+'shopify/products.jsonl'):
    d=json.loads(l)
    if 'sku' not in d: P[d['id']]=d['title']
desc={}
for v in V: desc[(P[v['__parentId']]+' '+v['title']).lower().replace(',','')]=canon(v['sku'])
# QuickBooks vendors
qb=list(csv.DictReader(open(EX+'quickbooks/vendors.csv')))
q=[]
for r in qb:
    m=re.fullmatch(r'sales@([a-z]+)\.example',r['Email'])
    if m: q.append(f(["supplier/code",m.group(1).upper()],"quickbooks/vendor",r['Vendor']))
write(q,'quickbooks/vendors.csv',0.9,label='qb suppliers')
q2=[f(["quickbooks/vendor",r['Vendor']],"quickbooks/vendor",r['Vendor']) for r in qb if not r['Email'].startswith('sales@')]
write(q2,'quickbooks/vendors.csv',label='qb forwarder/broker/3pl')
# factory docs: per-PDF
unm=[]
seen=set()
for fn in sorted(glob.glob(EX+'supplier_docs/CI-PL_*.pdf')):
    pre=os.path.basename(fn)[6:8]; sup=M[pre]
    txt=open(SCR+'/txt/'+os.path.basename(fn)[:-4]+'.txt').read().split('\n')
    facts=[]
    for i,l in enumerate(txt):
        m=re.match(r'^((?:[A-Z]{2}-?)?\d+) (.+)$',l)
        if m and i+2<len(txt):
            h=re.match(r'^(\d{4}\.\d{2}\.\d{4}) ',txt[i+2])
            if not h: continue
            d=m.group(2).lower().replace(',','')
            c=desc.get(d)
            if not c: unm.append((sup,m.group(1),d));continue
            if (sup,m.group(1)) in seen: continue
            seen.add((sup,m.group(1)))
            e=["sku/code",c]
            facts+=[f(e,"factory/item_code",sup+':'+m.group(1)),f(e,"sku/hs_code",h.group(1)),f(e,"sku/supplier",["supplier/code",sup])]
    if facts: write(facts,'supplier_docs/'+os.path.basename(fn),0.7,label=os.path.basename(fn))
print('unmatched',unm,len(seen))
