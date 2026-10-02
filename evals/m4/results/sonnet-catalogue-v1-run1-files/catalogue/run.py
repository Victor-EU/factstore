import os,sys,json,csv,re,hashlib,collections
import factstore
os.chdir('exports')
exec(open(os.environ['TMPDIR']+'/w/sku.py').read())
DRY = '--dry' in sys.argv
def sha(p): return hashlib.sha256(open(p,'rb').read()).hexdigest()
def tx(path, facts, conf):
    h=sha(path); d=['document/hash',h]
    facts=[{'e':d,'a':'document/url','v':path},
           {'e':'tmp:tx','a':'core/evidence','v':d},
           {'e':'tmp:tx','a':'core/confidence','v':str(conf)}]+facts
    r=factstore.transact(facts,dry_run=DRY); return r
def batched(path,facts,conf,n=4000):
    for i in range(0,len(facts),n):
        r=tx(path,facts[i:i+n],conf)
        print(path,conf,r.tx,sum(1 for x in r.lookups if x['created']),'created')
F=lambda e,a,v:{'e':e,'a':a,'v':v}
num=lambda g:g.rsplit('/',1)[1]
what=sys.argv[1]

bar={v['barcode']:v for v in vs}
hub={v['id']:norm(v['sku']) for v in vs}
if what=='sku':
    # exact: shopify variants (hub by Shopify variant + barcode), 3PL by UPC
    f=[]
    for v in vs:
        c=['sku/code',hub[v['id']]]
        f+=[F(c,'shopify/variant_id',num(v['id'])),F(c,'sku/upc',v['barcode']),F(c,'shopify/sku',v['sku'])]
    batched('shopify/products.jsonl',f,1)
    f=[]
    for r in tpl:
        v=bar[r['UPC']]; c=['sku/code',hub[v['id']]]
        f+=[F(c,'tpl/item_code',r['Item Code'])]
        if r['Client SKU']: f.append(F(c,'tpl/client_sku',r['Client SKU']))
    batched('3pl/inventory_snapshot.csv',f,1)
    # normalized: amazon
    f=[]
    for r in am:
        c=['sku/code',norm(r[0])]
        assert c[1] in set(hub.values())
        f+=[F(c,'amazon/seller_sku',r[0]),F(c,'amazon/fnsku',r[1]),F(c,'amazon/asin',r[2])]
    batched('amazon/fba_inventory.txt',f,0.9)
elif what=='factory':
    dm={desc(v):norm(v['sku']) for v in vs}
    for fn,pg in sorted(pdf.items()):
        if fn.startswith(('CI-PL','LCI')): continue
        p=PFX[fn[:2]]; f=[]
        for code,d,q in pi_items(pg[0]):
            f.append(F(['sku/code',dm[d]],'factory/item_code',p+':'+code))
        batched('supplier_docs/'+fn,f,0.7)
elif what=='supplier':
    sup=list(csv.DictReader(open('quickbooks/vendors.csv')))
    f=[]
    for r in sup:
        dom=r['Email'].split('@')[1].split('.')[0].upper()
        if dom in PFX.values(): f+=[F(['supplier/code',dom],'quickbooks/vendor_name',r['Vendor'])]; 
        else: f+=[F(['quickbooks/vendor_name',r['Vendor']],'quickbooks/vendor_name',r['Vendor'])]
    batched('quickbooks/vendors.csv',f,0.9)
elif what=='shipments':
    for fn,pg in sorted(pdf.items()):
        if not fn.startswith('CI-PL'): continue
        m=re.search(r'Container: (\S+)\s+B/L: (\S+)','\n'.join(pg)); cont,bl=m.groups()
        f=[F(['shipment/hbl',bl],'shipment/hbl',bl)]
        if cont!='LCL': f.append(F(['shipment/hbl',bl],'shipment/container_no',cont))
        batched('supplier_docs/'+fn,f,1)
elif what=='receipts':
    c2h={}
    for fn,pg in pdf.items():
        if fn.startswith('CI-PL'):
            cont,bl=re.search(r'Container: (\S+)\s+B/L: (\S+)','\n'.join(pg)).groups()
            if cont!='LCL': assert c2h.setdefault(cont,bl)==bl
    seen={}; f=[]; miss=set()
    for r in csv.DictReader(open('3pl/receipts.csv')):
        k=r['Receipt #']
        if k in seen: continue
        seen[k]=1; e=['tpl/receipt_no',k]
        f+=[F(e,'tpl/receipt_no',k),F(e,'tpl/asn_no',r['ASN #'])]
        cn=r['Container #']; hb=c2h.get(cn) or (cn if cn.startswith('PBLHB') else None)
        if hb: f.append(F(e,'tpl_receipt/shipment',['shipment/hbl',hb]))
        else: miss.add((k,r['Container #']))
    print('receipts without shipment',sorted(miss))
    batched('3pl/receipts.csv',f,1)
elif what=='fba':
    f=[]
    for r in csv.DictReader(open('amazon/fba_inbound_shipments.csv')): f.append(F(['amazon/fba_shipment_id',r['Shipment ID']],'amazon/fba_shipment_id',r['Shipment ID']))
    batched('amazon/fba_inbound_shipments.csv',f,1)
elif what=='amazon_orders':
    ids=[]; s=set()
    for l in list(open('amazon/all_orders.txt'))[1:]:
        i=l.split('\t')[0]
        if i not in s: s.add(i); ids.append(i)
    batched('amazon/all_orders.txt',[F(['amazon/order_id',i],'amazon/order_id',i) for i in ids],1)
elif what=='orders':
    f=[]; cust={}
    for l in open('shopify/orders.jsonl'):
        d=json.loads(l)
        if 'customer' not in d: continue
        o=['shopify/order_id',num(d['id'])]; c=num(d['customer']['id'])
        f+=[F(o,'shopify/order_id',num(d['id'])),F(o,'shopify/order_name',d['name']),F(o,'order/customer',['shopify/customer_id',c]),F(['shopify/customer_id',c],'shopify/customer_id',c)]
    batched('shopify/orders.jsonl',f,1,4000)
elif what=='dups':
    cust={}; addr=collections.defaultdict(set)
    for l in open('shopify/orders.jsonl'):
        d=json.loads(l)
        if 'customer' not in d: continue
        c=d['customer']; k=num(c['id'])
        if k not in cust: cust[k]=[c,d['createdAt']]
        a=d['shippingAddress'] or {}; addr[k].add((a.get('address1'),a.get('zip')))
    def ne(e):
        u,dm=e.lower().split('@'); u=u.split('+')[0]
        if dm in('gmail.com','googlemail.com'): u=u.replace('.','')
        return u+'@'+dm
    nm=lambda c:(c['firstName'].strip().lower(),c['lastName'].strip().lower())
    # edges: (k1,k2,conf)
    par={k:k for k in cust}
    def find(x):
        while par[x]!=x: par[x]=par[par[x]]; x=par[x]
        return x
    grp=collections.defaultdict(set)
    for k,(c,t) in cust.items():
        grp[('m',ne(c['email']))+nm(c)].add(k)
        for a in addr[k]: grp[('a',)+nm(c)+a].add(k)
    conf={}
    for key,v in grp.items():
        if len(v)<2: continue
        v=sorted(v,key=lambda k:(cust[k][1],k)); s=v[0]
        for k in v[1:]:
            exact = key[0]=='m' and len({cust[x][0]['email'] for x in v})==1
            # survivor: earliest account
            conf.setdefault(k,{})[s]=max(conf.get(k,{}).get(s,0),1 if exact else 0.9)
    # resolve chains: follow to root survivor
    tgt={}
    for k,m in conf.items(): tgt[k]=min(m,key=lambda s:(cust[s][1],s))
    def root(k):
        seen=set()
        while k in tgt and k not in seen: seen.add(k); k=tgt[k]
        return k
    out=collections.defaultdict(list)
    for k in tgt:
        r=root(k)
        if r==k: continue
        out[conf[k][tgt[k]]].append(F(['shopify/customer_id',k],'core/same_as',['shopify/customer_id',r]))
    for cf,f in sorted(out.items()): batched('shopify/orders.jsonl',f,cf)
    print({k:len(v) for k,v in out.items()})
