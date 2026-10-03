import json,csv,re,glob,hashlib,sys,os,collections as C
import factstore
EX='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-m-l3ll44x6/catalogue/work/exports'
S=os.path.dirname(os.path.abspath(__file__))
DRY='--dry' in sys.argv
LIMIT=int(sys.argv[sys.argv.index('--limit')+1]) if '--limit' in sys.argv else None
def sha(p): return hashlib.sha256(open(p,'rb').read()).hexdigest()
def doc(rel):
    h=sha(f'{EX}/{rel}')
    return h,[{"e":["document/hash",h],"a":"document/url","v":rel}]
def write(facts,rel,conf=None,batch=4000,unit=None):
    """facts: list of fact-groups (lists) kept whole within a batch"""
    h,df=doc(rel); n=0; cur=[]
    def flush():
        nonlocal cur,n
        if not cur: return
        f=[x for g in cur for x in g]+df+[{"e":"tmp:tx","a":"core/evidence","v":["document/hash",h]}]
        if conf is not None: f.append({"e":"tmp:tx","a":"core/confidence","v":str(conf)})
        r=factstore.transact(f,dry_run=DRY); n+=len(cur); cur=[]
    sz=0
    for g in facts:
        cur.append(g); sz+=len(g)
        if sz>=batch: flush(); sz=0
    flush(); print('wrote',rel,n,'groups conf',conf,flush=True)
def F(e,a,v): return {"e":e,"a":a,"v":v}
def num(gid): return gid.rsplit('/',1)[1]

# ---------- sources
prod=[json.loads(l) for l in open(f'{EX}/shopify/products.jsonl')]
var=[p for p in prod if 'ProductVariant' in p['id']]
pat=re.compile(r'^AH-[A-Z]{3}-\d{4}-[A-Z]{3}$')
def clean(code):
    if pat.match(code): return code
    m=re.match(r'^AH-?([A-Z]{3})-?(\d+)-?([A-Z]{3})$',code.upper())
    assert m,code
    return f'AH-{m[1]}-{int(m[2]):04d}-{m[3]}'
hub={}   # variant gid -> clean code
for v in var: hub[v['id']]=clean(v['sku'])
assert len(set(hub.values()))==49
hubs=set(hub.values())
upc2hub={v['barcode']:hub[v['id']] for v in var}
assert len(upc2hub)==49

stage=sys.argv[1]
if stage=='hubs':
    ok=[];bad=[]
    for v in var:
        g=[F(["sku/code",hub[v['id']]],"shopify/variant_id",num(v['id'])),F(["sku/code",hub[v['id']]],"sku/upc",v['barcode'])]
        (ok if pat.match(v['sku']) else bad).append(g)
    write(ok,'shopify/products.jsonl',1)
    write(bad,'shopify/products.jsonl',0.9)
    # 3PL item codes by exact UPC
    inv=list(csv.DictReader(open(f'{EX}/3pl/inventory_snapshot.csv')))
    g=[[F(["sku/code",upc2hub[r['UPC']]],"tpl/item_code",r['Item Code'])] for r in inv]
    write(g,'3pl/inventory_snapshot.csv',1)
    # cross-check 3PL client SKU spelling
    for r in inv:
        c=r['Client SKU']
        if c and c!=upc2hub[r['UPC']]: print('3pl spelling differs',c,upc2hub[r['UPC']])
if stage=='suppliers':
    qb=list(csv.DictReader(open(f'{EX}/quickbooks/vendors.csv')))
    names={}
    for f in glob.glob(S+'/txt/*'):
        t=open(f).read()
        m=re.search(r'Email: sales@(\w+)\.example',t)
        if m and 'COMMERCIAL INVOICE' in t: names[t.split('\n')[1].strip().upper()]=m[1].upper()
    g=[];nosup=[]
    for r in qb:
        code=names.get(r['Company name'].upper())
        dom=r['Email'].split('@')[1].split('.')[0].upper() if r['Email'] else None
        if code:
            assert dom==code,(r,code)
            g.append([F(["supplier/code",code],"quickbooks/vendor",r['Vendor'])])
        else: nosup.append(r['Vendor'])
    write(g,'quickbooks/vendors.csv',0.9)
    write([[F(["quickbooks/vendor",v],"quickbooks/vendor",v)] for v in nosup],'quickbooks/vendors.csv',1)
    print('non-supplier vendors',nosup)
if stage=='factory':
    items={}  # (dom,code)->(desc,hs,doc)
    for f in sorted(glob.glob(S+'/txt/*')):
        t=open(f).read()
        if 'COMMERCIAL INVOICE' not in t: continue
        dom=re.search(r'Email: sales@(\w+)\.example',t)[1].upper()
        L=t.split('\n')
        for i in range(len(L)-2):
            if re.match(r'^\d{4}\.\d{2}\.\d{4} ',L[i+2]) and not L[i].startswith(('Item','TOTAL')):
                code,desc=L[i].split(' ',1)
                items.setdefault((dom,code),(desc.strip().lower(),L[i+2].split()[0],os.path.basename(f)[:-4]))
    title={}
    for p in prod:
        if 'ProductVariant' not in p['id']: title[p['id']]=None
    ptitle={p['id']:p['title'] for p in prod if 'ProductVariant' not in p['id']}
    desc2sku={}
    for v in var:
        d=(ptitle[v['__parentId']]+' '+v['title']).lower()
        assert d not in desc2sku; desc2sku[d]=hub[v['id']]
    out=[];fam=C.defaultdict(set);used=set()
    for (dom,code),(d,hs,pdf) in sorted(items.items()):
        sku=desc2sku[d]; assert sku not in used; used.add(sku)
        fam[dom].add(sku.split('-')[1])
        out.append(([F(["sku/code",sku],"factory/item_code",f'{dom}:{code}'),F(["sku/code",sku],"sku/supplier",["supplier/code",dom]),F(["sku/code",sku],"sku/hs_code",hs)],pdf))
        print(dom,code,d,'->',sku,hs)
    assert used==hubs, hubs-used
    print({k:sorted(v) for k,v in fam.items()})
    for g,pdf in out:
        write([g],'supplier_docs/'+pdf,0.7)
if stage=='amazon':
    inv=list(csv.DictReader(open(f'{EX}/amazon/fba_inventory.txt'),delimiter='\t'))
    ex=[];nm=[];core=[]
    for r in inv:
        s=r['sku']; core.append([F(["amazon/seller_sku",s],"listing/asin",["amazon/asin",r['asin']]),F(["amazon/seller_sku",s],"amazon/fnsku",r['fnsku'])])
        if s in hubs: ex.append([F(["amazon/seller_sku",s],"listing/sku",["sku/code",s])])
        else:
            b=re.sub(r'-FBA$','',s); assert b in hubs,s
            nm.append([F(["amazon/seller_sku",s],"listing/sku",["sku/code",b])])
    write(core,'amazon/fba_inventory.txt',1)
    write(ex,'amazon/fba_inventory.txt',1)
    write(nm,'amazon/fba_inventory.txt',0.9)
    # check one listing per hub
    tgt=C.Counter(g[0]['v'][1] for g in ex+nm); print('hubs with >1 listing',[k for k,v in tgt.items() if v>1],'hubs with listing',len(tgt))
    fb=list(csv.DictReader(open(f'{EX}/amazon/fba_inbound_shipments.csv')))
    write([[F(["amazon/fba_shipment_id",r['Shipment ID']],"amazon/fba_shipment_id",r['Shipment ID'])] for r in fb],'amazon/fba_inbound_shipments.csv',1)
    ao=list(csv.DictReader(open(f'{EX}/amazon/all_orders.txt'),delimiter='\t'))
    sk={r['sku'] for r in inv}; assert {r['sku'] for r in ao}<=sk
    seen=set();g=[]
    for r in ao:
        o=r['amazon-order-id']; oe=["amazon/order_id",o]
        grp=[]
        if o not in seen: seen.add(o); grp.append(F(oe,"amazon/order_id",o))
        le=["amazon/order_line",f"{o}/{r['sku']}"]
        grp+= [F(le,"amazon/order_line",f"{o}/{r['sku']}"),F(le,"core/part_of",oe),F(le,"line/listing",["amazon/seller_sku",r['sku']])]
        g.append(grp)
    if LIMIT: g=g[:LIMIT]
    write(g,'amazon/all_orders.txt',1)
if stage=='shopify':
    orders=[];lines=[]
    for l in open(f'{EX}/shopify/orders.jsonl'):
        d=json.loads(l); (lines if 'LineItem' in d['id'] else orders).append(d)
    vids={num(v['id']) for v in var}
    assert all(num(l['variant']['id']) in vids for l in lines)
    og=[]
    for o in orders:
        oe=["shopify/order_id",num(o['id'])]
        og.append([F(oe,"shopify/order_id",num(o['id'])),F(oe,"shopify/order_name",o['name']),F(oe,"order/customer",["shopify/customer_id",num(o['customer']['id'])])])
    lg=[]
    for l in lines:
        le=["shopify/line_item_id",num(l['id'])]
        lg.append([F(le,"shopify/line_item_id",num(l['id'])),F(le,"core/part_of",["shopify/order_id",num(l['__parentId'])]),F(le,"line/sku",["shopify/variant_id",num(l['variant']['id'])])])
    if LIMIT: og=og[:LIMIT]; lg=lg[:LIMIT]
    write(og,'shopify/orders.jsonl',1); write(lg,'shopify/orders.jsonl',1)
if stage=='tpl':
    ob=list(csv.DictReader(open(f'{EX}/3pl/outbound.csv')))
    g=[]
    for r in ob:
        ref=r['Order Reference']; k=f"{ref}/{r['Item Code']}"
        whole=["shopify/order_name",ref] if ref.startswith('#') else ["amazon/fba_shipment_id",ref]
        le=["tpl/outbound_line",k]
        g.append([F(le,"tpl/outbound_line",k),F(le,"core/part_of",whole),F(le,"line/sku",["tpl/item_code",r['Item Code']])])
    if LIMIT: g=g[:LIMIT]
    write(g,'3pl/outbound.csv',1)
    rc=list(csv.DictReader(open(f'{EX}/3pl/receipts.csv')))
    g=[];seen=set()
    for r in rc:
        re_=["tpl/receipt_no",r['Receipt #']]; grp=[]
        if r['Receipt #'] not in seen:
            seen.add(r['Receipt #']); grp.append(F(re_,"tpl/receipt_no",r['Receipt #']))
            for p in r['Reference'].split(' / '):
                if p: assert re.match(r'^PO-\d{4}-\d{4}$',p),p
        k=f"{r['Receipt #']}/{r['Item Code']}"; le=["tpl/receipt_line",k]
        grp+=[F(le,"tpl/receipt_line",k),F(le,"core/part_of",re_),F(le,"line/sku",["tpl/item_code",r['Item Code']])]
        g.append(grp)
    # receipt/po once per receipt
    rp={}
    for r in rc:
        ps=[p for p in r['Reference'].split(' / ') if p]
        rp.setdefault(r['Receipt #'],set()).update(ps)
    g+= [[F(["tpl/receipt_no",k],"receipt/po",["po/number",p]) for p in sorted(v)] for k,v in rp.items() if v]
    write(g,'3pl/receipts.csv',1)
