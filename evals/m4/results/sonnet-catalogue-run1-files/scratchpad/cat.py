import os,sys,json,csv,re,glob,hashlib,collections
import factstore, pypdf
EX='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m4-catalogue-jr3lchtv/work/exports'
os.chdir(EX)
DRY='--dry' in sys.argv
BATCH=3000
def sha(p): return hashlib.sha256(open(p,'rb').read()).hexdigest()
DOC={}
def docfacts(p):
    if p not in DOC: DOC[p]=sha(p)
    h=DOC[p]
    return [{"e":["document/hash",h],"a":"document/url","v":p},
            {"e":"tmp:tx","a":"core/evidence","v":["document/hash",h]}]
stats=collections.Counter()
def tx(facts,path,conf=None,per=BATCH):
    """write facts in batches; each batch is its own transaction. facts must not split an entity's..."""
    for i in range(0,len(facts),per):
        chunk=facts[i:i+per]+docfacts(path)
        if conf is not None: chunk.append({"e":"tmp:tx","a":"core/confidence","v":str(conf)})
        r=factstore.transact(chunk,dry_run=DRY)
        stats['tx']+=1
    return
def gid(s): return s.rsplit('/',1)[1]
def canon(sku):
    s=sku.upper()
    m=re.fullmatch(r'AH-?([A-Z]{3})-?(\d{1,4})-?([A-Z]{3})',s)
    assert m,sku
    return f'AH-{m.group(1)}-{int(m.group(2)):04d}-{m.group(3)}'
# ---- load
prods={};par={}
for l in open('shopify/products.jsonl'):
    d=json.loads(l)
    (prods if 'sku' in d else par)[d['id']]=d
hub={}   # shopify sku spelling -> canonical
upc2hub={}
vid2hub={}
for v in prods.values():
    c=canon(v['sku']); hub[v['sku']]=c; upc2hub[v['barcode']]=c; vid2hub[v['id']]=c
assert len(set(hub.values()))==49==len(set(upc2hub.values()))
phase=[a for a in sys.argv[1:] if not a.startswith('--')]
def run(n): return not phase or n in phase

if run('hubs'):
    for tier,conf in (('exact',1),('norm',0.9)):
        f=[]
        for v in prods.values():
            c=hub[v['sku']]; isx=(v['sku']==c)
            if isx!=(tier=='exact'): continue
            f+=[{"e":["sku/code",c],"a":"sku/code","v":c},
                {"e":["sku/code",c],"a":"sku/upc","v":v['barcode']},
                {"e":["sku/code",c],"a":"shopify/variant_id","v":gid(v['id'])}]
        print(tier,len(f)//3); tx(f,'shopify/products.jsonl',conf)
if run('tpl_items'):
    f=[]
    for r in csv.DictReader(open('3pl/inventory_snapshot.csv')):
        f.append({"e":["sku/upc",r['UPC']],"a":"tpl/item_code","v":r['Item Code']})
    assert len({x['v'] for x in f})==49 and all(x['e'][1] in upc2hub for x in f)
    tx(f,'3pl/inventory_snapshot.csv',1)
if run('amazon_items'):
    inv=list(csv.DictReader(open('amazon/fba_inventory.txt'),delimiter='\t'))
    hs=collections.Counter()
    ex=[];nm=[]
    for r in inv:
        s=r['sku']; c=re.sub(r'-FBA$','',s); assert c in upc2hub.values(),s
        hs[c]+=1
        L=ex if s==c else nm
        L+= [{"e":["sku/code",c],"a":a,"v":v} for a,v in (("amazon/seller_sku",s),("amazon/asin",r['asin']),("amazon/fnsku",r['fnsku']))]
    assert max(hs.values())==1
    print(len(ex)//3,len(nm)//3)
    tx(ex,'amazon/fba_inventory.txt',1); tx(nm,'amazon/fba_inventory.txt',0.9)
# amazon seller sku -> hub
def az2hub(s): return re.sub(r'-FBA$','',s)
# ---- supplier / factory
PRE={'MT':'NBBW','HT':'SZHT','LX':'YWLX','RF':'DGRF','MJ':'FSMJ','YD':'XMYD','QS':'NBQS','TY':'HZTY'}
titles={}
for v in prods.values():
    titles[(par[v['__parentId']]['title']+' '+v['title']).lower().replace(',','')]=hub[v['sku']]
if run('factory'):
    seen={}
    for p in sorted(glob.glob('supplier_docs/CI-PL*.pdf')):
        sup=PRE[os.path.basename(p).split('_')[1][:2]]
        t='\n'.join(x.extract_text() for x in pypdf.PdfReader(p).pages); L=t.split('\n'); f=[]
        for i,l in enumerate(L):
            m=re.match(r'^([A-Z]{0,2}-?\d{3,5}) (.+)$',l)
            if not(m and i+2<len(L)): continue
            hsm=re.match(r'^(\d{4}\.\d{2}\.\d{4}) ',L[i+2])
            if not hsm: continue
            code=sup+':'+m.group(1); 
            if code in seen: assert seen[code]==(m.group(2),hsm.group(1)); continue
            seen[code]=(m.group(2),hsm.group(1))
            h=titles[m.group(2).replace(',','')]
            e=["sku/code",h]
            f+=[{"e":e,"a":"factory/item_code","v":code},{"e":e,"a":"sku/supplier","v":["supplier/code",sup]},{"e":e,"a":"sku/hs_code","v":hsm.group(1)}]
        if f: tx(f,p,0.7)
    assert len(seen)==49 and len({titles[d.replace(',','')] for d,_ in seen.values()})==49
    print('factory',len(seen))
if run('qb'):
    vend=list(csv.DictReader(open('quickbooks/vendors.csv')))
    mp={'Mingtu Housewares':'NBBW','Hetai Electric (SZ)':'SZHT','Lanxin Textile':'YWLX','Ruifeng Silicone':'DGRF','Mingjia Ceramics':'FSMJ','Yuanda Bamboo':'XMYD','Qisheng Stainless':'NBQS','Tianyi Glassware':'HZTY'}
    f=[]
    for r in vend:
        e=["quickbooks/vendor_name",r['Vendor']]
        f.append({"e":e,"a":"quickbooks/vendor_name","v":r['Vendor']})
    tx(f,'quickbooks/vendors.csv')
    f=[]
    for r in vend:
        if r['Vendor'] in mp:
            c=mp[r['Vendor']]; assert r['Email'].split('@')[1].startswith(c.lower()+'.')
            f.append({"e":["quickbooks/vendor_name",r['Vendor']],"a":"vendor/supplier","v":["supplier/code",c]})
    tx(f,'quickbooks/vendors.csv',1)
# ---- shopify
def load_orders():
    orders=[];lines=[]
    for l in open('shopify/orders.jsonl'):
        d=json.loads(l); (lines if '__parentId' in d else orders).append(d)
    return orders,lines
if run('customers') or run('orders') or run('lines'):
    orders,lines=load_orders()
if run('customers'):
    first={}
    info={}
    for o in orders:
        c=o['customer']; cid=gid(c['id'])
        if cid not in first or o['createdAt']<first[cid]: first[cid]=o['createdAt']
        info.setdefault(cid,(c['email'],c['firstName'],c['lastName'],o['shippingAddress']['address1'],o['shippingAddress']['zip']))
    tx([{"e":["shopify/customer_id",c],"a":"shopify/customer_id","v":c} for c in sorted(first)],'shopify/orders.jsonl')
    def norm(e):
        loc,_,dom=e.lower().partition('@'); loc=loc.split('+')[0]
        if dom in('gmail.com','googlemail.com'): loc=loc.replace('.','')
        return loc+'@'+dom
    # union-find on strong evidence
    parent={c:c for c in first}
    def find(x):
        while parent[x]!=x: parent[x]=parent[parent[x]]; x=parent[x]
        return x
    keys=collections.defaultdict(list)
    for c,(e,fn,ln,a,z) in info.items():
        keys[('e',norm(e))].append(c); keys[('n',fn.lower(),ln.lower(),a.lower(),z)].append(c)
    for k,v in keys.items():
        for x in v[1:]: parent[find(x)]=find(v[0])
    cl=collections.defaultdict(list)
    for c in first: cl[find(c)].append(c)
    s9=[];s7=[];unr=0
    for m in cl.values():
        if len(m)<2: continue
        m.sort(key=lambda c:(first[c],c)); sv=m[0]
        for c in m[1:]:
            ie,i=info[c],info[sv]
            if norm(ie[0])==norm(i[0]): s9.append((c,sv))
            elif ie[1:]==i[1:] or (ie[1].lower(),ie[2].lower(),ie[3].lower(),ie[4])==(i[1].lower(),i[2].lower(),i[3].lower(),i[4]): s7.append((c,sv))
            else: unr+=1; print('unresolved chain',c,sv)
    print('same_as',len(s9),len(s7),'unresolved',unr,'clusters',sum(1 for m in cl.values() if len(m)>1))
    json.dump({'s9':s9,'s7':s7},open(os.environ['TMPDIR']+'/dups.json','w'))
    tx([{"e":["shopify/customer_id",a],"a":"core/same_as","v":["shopify/customer_id",b]} for a,b in s9],'shopify/orders.jsonl',0.9)
    tx([{"e":["shopify/customer_id",a],"a":"core/same_as","v":["shopify/customer_id",b]} for a,b in s7],'shopify/orders.jsonl',0.7)
if run('orders'):
    f=[]
    for o in orders:
        e=["shopify/order_id",gid(o['id'])]
        f+=[{"e":e,"a":"shopify/order_id","v":gid(o['id'])},{"e":e,"a":"order/customer","v":["shopify/customer_id",gid(o['customer']['id'])]}]
    tx(f,'shopify/orders.jsonl',per=3000)
if run('lines'):
    f=[]
    for x in lines:
        e=["shopify/line_item_id",gid(x['id'])]
        f+=[{"e":e,"a":"shopify/line_item_id","v":gid(x['id'])},{"e":e,"a":"core/part_of","v":["shopify/order_id",gid(x['__parentId'])]},
            {"e":e,"a":"line/sku","v":["sku/code",vid2hub[x['variant']['id']]]}]
    tx(f,'shopify/orders.jsonl',per=3000)
# ---- amazon
if run('az'):
    rows=list(csv.DictReader(open('amazon/all_orders.txt'),delimiter='\t'))
    f=[];seen=set()
    for r in rows:
        o=r['amazon-order-id']; k=o+'/'+r['sku']; assert k not in seen; seen.add(k)
        f+=[{"e":["amazon/order_id",o],"a":"amazon/order_id","v":o},{"e":["amazon/order_line",k],"a":"amazon/order_line","v":k},
            {"e":["amazon/order_line",k],"a":"core/part_of","v":["amazon/order_id",o]},{"e":["amazon/order_line",k],"a":"line/sku","v":["sku/code",az2hub(r['sku'])]}]
    tx(f,'amazon/all_orders.txt',per=3000)
    f=[{"e":["amazon/fba_shipment_id",r['Shipment ID']],"a":"amazon/fba_shipment_id","v":r['Shipment ID']} for r in csv.DictReader(open('amazon/fba_inbound_shipments.csv'))]
    tx(f,'amazon/fba_inbound_shipments.csv')
# ---- 3pl
if run('tpl'):
    rec=list(csv.DictReader(open('3pl/receipts.csv')))
    docs=collections.defaultdict(list)
    for p in sorted(glob.glob('supplier_docs/CI-PL*.pdf')):
        t=pypdf.PdfReader(p).pages[0].extract_text()
        m=re.search(r'Order: (.+?)\s+From .*Container: (\S+)\s+B/L: (\S+)',t)
        docs[m.group(2)].append(({x.strip() for x in m.group(1).split('/')},m.group(3)))
    base=[];ship={'lcl':[],'cp':[],'c1':[]};unres=[]
    byr=collections.defaultdict(list)
    for r in rec: byr[r['Receipt #']].append(r)
    for rn,rs in byr.items():
        e=["tpl/receipt_no",rn]
        base.append({"e":e,"a":"tpl/receipt_no","v":rn})
        pos=set()
        for r in rs:
            for p in r['Reference'].split('/'):
                p=p.strip()
                if p: assert re.fullmatch(r'PO-\d{4}-\d{4}',p),p; pos.add(p)
        for p in sorted(pos): base.append({"e":e,"a":"receipt/po","v":["po/number",p]})
        cs={r['Container #'] for r in rs}; assert len(cs)==1; c=cs.pop()
        if c.startswith('PBLHB'): ship['lcl'].append({"e":e,"a":"receipt/shipment","v":["shipment/hbl",c]})
        else:
            cand=docs.get(c,[])
            m={b for ps,b in cand if ps&pos}
            if len(m)==1: ship['cp'].append({"e":e,"a":"receipt/shipment","v":["shipment/hbl",m.pop()]})
            elif not pos and len({b for _,b in cand})==1: ship['c1'].append({"e":e,"a":"receipt/shipment","v":["shipment/hbl",cand[0][1]]})
            else: unres.append((rn,c))
    for r in rec:
        k=r['Receipt #']+'/'+r['Item Code']; e=["tpl/receipt_line",k]
        base+=[{"e":e,"a":"tpl/receipt_line","v":k},{"e":e,"a":"core/part_of","v":["tpl/receipt_no",r['Receipt #']]},{"e":e,"a":"line/sku","v":["tpl/item_code",r['Item Code']]}]
    tx(base,'3pl/receipts.csv')
    tx(ship['lcl'],'3pl/receipts.csv',1); tx(ship['cp']+ship['c1'],'3pl/receipts.csv',0.7)
    print({k:len(v) for k,v in ship.items()},'unresolved',unres)
    names={}
    for l in open('shopify/orders.jsonl'):
        d=json.loads(l)
        if 'customer' in d: names[d['name']]=gid(d['id'])
    f=[]
    for r in csv.DictReader(open('3pl/outbound.csv')):
        ref=r['Order Reference']; k=ref+'/'+r['Item Code']; e=["tpl/outbound_line",k]
        whole=["shopify/order_id",names[ref]] if ref.startswith('#') else ["amazon/fba_shipment_id",ref]
        f+=[{"e":e,"a":"tpl/outbound_line","v":k},{"e":e,"a":"core/part_of","v":whole},{"e":e,"a":"line/sku","v":["tpl/item_code",r['Item Code']]}]
    tx(f,'3pl/outbound.csv',per=3000)
print(dict(stats),'DRY' if DRY else '')
