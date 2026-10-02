import sys;sys.path.insert(0,'scripts')
from common import *
DRY='--dry' in sys.argv
prods,vars_=shopify_products()
def norm(s): return re.sub(r'\s+',' ',s.lower().replace(',','').replace('(','').replace(')','')).strip()
hub={}  # code -> dict
for v in vars_:
    c=hub_code(v['sku']); assert c not in hub
    hub[c]=dict(upc=v['barcode'],variant=gid(v['id']),exact=(v['sku']==c),desc=norm(prods[v['__parentId']]['title']+' '+v['title']))
tpl={r['UPC']:r['Item Code'] for r in csv.DictReader(open(EX+'3pl/inventory_snapshot.csv'))}
for c,h in hub.items(): h['tpl']=tpl[h['upc']]
assert len(set(h['tpl'] for h in hub.values()))==49
for r in csv.DictReader(open(EX+'amazon/fba_inventory.txt'),delimiter='\t'):
    c=hub_code(r['sku']); assert 'amz' not in hub[c]
    hub[c]['amz']=dict(sku=r['sku'],asin=r['asin'],fnsku=r['fnsku'],exact=(r['sku']==c))
# suppliers
codes={'Mingtu Housewares':'NBBW','Hetai Electric (SZ)':'SZHT','Lanxin Textile':'YWLX','Ruifeng Silicone':'DGRF','Mingjia Ceramics':'FSMJ','Yuanda Bamboo':'XMYD','Qisheng Stainless':'NBQS','Tianyi Glassware':'HZTY'}
qb=list(csv.DictReader(open(EX+'quickbooks/vendors.csv')))
f_sup=[];f_other=[]
for r in qb:
    if r['Vendor'] in codes:
        c=codes[r['Vendor']]; assert r['Email'].split('@')[1].split('.')[0]==c.lower()
        f_sup.append({'e':['supplier/code',c],'a':'quickbooks/vendor','v':r['Vendor']})
    else: f_other.append({'e':['quickbooks/vendor',r['Vendor']],'a':'quickbooks/vendor','v':r['Vendor']})
write(f_sup,['quickbooks/vendors.csv'],0.9,dry=DRY)
write(f_other,['quickbooks/vendors.csv'],1,dry=DRY)
# hubs tier exact
t1=[];t2=[]
for c,h in hub.items():
    e=['sku/code',c]
    t1+= [{'e':e,'a':'sku/code','v':c},{'e':e,'a':'sku/upc','v':h['upc']},{'e':e,'a':'tpl/item_code','v':h['tpl']}]
    (t1 if h['exact'] else t2).append({'e':e,'a':'shopify/variant_id','v':h['variant']})
    a=h['amz'] if 'amz' in h else None
    if a:
        tgt=t1 if a['exact'] else t2
        tgt+= [{'e':e,'a':'amazon/seller_sku','v':a['sku']},{'e':e,'a':'amazon/asin','v':a['asin']},{'e':e,'a':'amazon/fnsku','v':a['fnsku']}]
srcs=['shopify/products.jsonl','3pl/inventory_snapshot.csv','amazon/fba_inventory.txt']
write(t1,srcs,1,dry=DRY); write(t2,srcs,0.9,dry=DRY)
print('hubs',len(hub),'exact-tier facts',len(t1),'normalized-tier facts',len(t2))
# factory items from CI-PL docs
pre={'MT':'NBBW','HT':'SZHT','LX':'YWLX','RF':'DGRF','MJ':'FSMJ','YD':'XMYD','QS':'NBQS','TY':'HZTY'}
import pypdf
bydesc={h['desc']:c for c,h in hub.items()}
fac={}  # code:item -> dict
docs=collections.defaultdict(set)
for f in sorted(glob.glob(EX+'supplier_docs/CI-PL_*.pdf')):
    sup=pre[os.path.basename(f).split('_')[1][:2]]
    t=[]
    for p in pypdf.PdfReader(f).pages: t+=p.extract_text().split('\n')
    for i,l in enumerate(t):
        m=re.match(r'^([A-Za-z0-9-]{2,12})\s+([a-z].*)$',l)
        if m and i+2<len(t):
            h=re.match(r'^(\d{4}\.\d{2}\.\d{4})\s',t[i+2])
            if h:
                k=f'{sup}:{m.group(1)}'; d=fac.setdefault(k,dict(desc=norm(m.group(2)),hs=set(),sup=sup))
                assert d['desc']==norm(m.group(2)); d['hs'].add(h.group(1)); docs[sup].add('supplier_docs/'+os.path.basename(f))
assert len(fac)==49 and all(len(d['hs'])==1 for d in fac.values())
skus=[bydesc[d['desc']] for d in fac.values()]; assert len(set(skus))==49
for sup in sorted(docs):
    facts=[]
    for k,d in fac.items():
        if d['sup']!=sup: continue
        e=['sku/code',bydesc[d['desc']]]
        facts+=[{'e':e,'a':'factory/item_code','v':k},{'e':e,'a':'sku/supplier','v':['supplier/code',sup]},{'e':e,'a':'sku/hs_code','v':list(d['hs'])[0]}]
    write(facts,sorted(docs[sup]),0.7,dry=DRY)
    print(sup,len(facts)//3,'items',len(docs[sup]),'docs')
