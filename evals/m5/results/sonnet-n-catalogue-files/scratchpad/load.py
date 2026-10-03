import json,csv,re,sys,hashlib,glob,os,collections as C
import factstore
EX='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-n-a32dezqd/catalogue/work/exports/'
LIMIT=int(sys.argv[2]) if len(sys.argv)>2 else None   # row limit for sampling
STEP=sys.argv[1]
def sha(rel): return hashlib.sha256(open(EX+rel,'rb').read()).hexdigest()
def write(facts,rel,conf=None,chunk=2500):
    h=sha(rel)
    for i in range(0,len(facts),chunk):
        part=facts[i:i+chunk]
        extra=[{"e":["document/hash",h],"a":"document/url","v":rel},
               {"e":"tmp:tx","a":"core/evidence","v":["document/hash",h]}]
        if conf is not None: extra.append({"e":"tmp:tx","a":"core/confidence","v":str(conf)})
        r=factstore.transact(part+extra)
        print(rel,conf,i,len(part),r if not hasattr(r,'tx') else r.tx,flush=True)
def F(e,a,v): return {"e":e,"a":a,"v":v}
def gid(s): return s.rsplit('/',1)[1]
def canon(s):
    m=re.fullmatch(r'AH-?([A-Z]{3})-?0*(\d+)-?([A-Z]{3})',s.upper()); return f"AH-{m[1]}-{int(m[2]):04d}-{m[3]}"
def cut(rows): return rows[:LIMIT] if LIMIT else rows

if STEP=='hubs':
    ex=[];odd=[];
    for l in open(EX+'shopify/products.jsonl'):
        r=json.loads(l)
        if 'sku' not in r: continue
        c=canon(r['sku']); 
        fs=[F(["sku/code",c],"sku/upc",r['barcode']),F(["sku/code",c],"shopify/variant_id",gid(r['id']))]
        (ex if c==r['sku'] else odd).extend(fs)
    write(ex,'shopify/products.jsonl',1); write(odd,'shopify/products.jsonl',0.9)
    # 3PL items by UPC (exact)
    fs=[F(["sku/upc",r['UPC']],"tpl/item_code",r['Item Code']) for r in csv.DictReader(open(EX+'3pl/inventory_snapshot.csv'))]
    write(fs,'3pl/inventory_snapshot.csv',1)
    # amazon listings
    ex=[];fba=[]
    for r in csv.DictReader(open(EX+'amazon/fba_inventory.txt'),delimiter='\t'):
        s=r['sku'];L=["amazon/seller_sku",s];hub=re.sub(r'-FBA$','',s)
        fs=[F(L,"listing/asin",["amazon/asin",r['asin']]),F(L,"amazon/fnsku",r['fnsku']),F(L,"listing/sku",["sku/code",canon(hub)])]
        (fba if s.endswith('-FBA') else ex).extend(fs)
        assert canon(hub)==hub or True
    write(ex,'amazon/fba_inventory.txt',1); write(fba,'amazon/fba_inventory.txt',0.9)
    fs=[F(["amazon/fba_shipment_id",r['Shipment ID']],"core/evidence_placeholder","x") for r in []]
    fs=[F(["amazon/fba_shipment_id",r['Shipment ID']],"amazon/fba_shipment_id",r['Shipment ID']) for r in csv.DictReader(open(EX+'amazon/fba_inbound_shipments.csv'))]
    write(fs,'amazon/fba_inbound_shipments.csv',1)

if STEP=='shopify':
    fs=[];n=0;seen=set()
    for l in open(EX+'shopify/orders.jsonl'):
        r=json.loads(l)
        if 'quantity' in r and 'sku' in r:
            L=["shopify/line_item_id",gid(r['id'])]
            fs+= [F(L,"shopify/line_item_id",gid(r['id'])),F(L,"core/part_of",["shopify/order_id",gid(r['__parentId'])]),F(L,"line/sku",["shopify/variant_id",gid(r['variant']['id'])])]
        else:
            n+=1
            if LIMIT and n>LIMIT: break
            O=["shopify/order_id",gid(r['id'])]
            fs+=[F(O,"shopify/order_id",gid(r['id'])),F(O,"shopify/order_name",r['name']),F(O,"order/customer",["shopify/customer_id",gid(r['customer']['id'])]),
                 F(["shopify/customer_id",gid(r['customer']['id'])],"shopify/customer_id",gid(r['customer']['id']))]
    write(fs,'shopify/orders.jsonl',1)

if STEP=='amazon':
    fs=[];seen=set()
    for r in cut(list(csv.DictReader(open(EX+'amazon/all_orders.txt'),delimiter='\t'))):
        o=r['amazon-order-id'];O=["amazon/order_id",o];L=["amazon/order_line",o+'/'+r['sku']]
        if o not in seen: seen.add(o); fs.append(F(O,"amazon/order_id",o))
        fs+=[F(L,"amazon/order_line",o+'/'+r['sku']),F(L,"core/part_of",O),F(L,"line/listing",["amazon/seller_sku",r['sku']])]
    write(fs,'amazon/all_orders.txt',1)

if STEP=='3pl':
    fs=[];seen=set()
    for r in cut(list(csv.DictReader(open(EX+'3pl/receipts.csv')))):
        R=["tpl/receipt_no",r['Receipt #']];L=["tpl/receipt_line",r['Receipt #']+'/'+r['Item Code']]
        if r['Receipt #'] not in seen:
            seen.add(r['Receipt #']); fs.append(F(R,"tpl/receipt_no",r['Receipt #']))
            for p in r['Reference'].split('/'):
                if p.strip(): fs.append(F(R,"receipt/po",["po/number",p.strip()]))
        fs+=[F(L,"tpl/receipt_line",r['Receipt #']+'/'+r['Item Code']),F(L,"core/part_of",R),F(L,"line/sku",["tpl/item_code",r['Item Code']])]
    write(fs,'3pl/receipts.csv',1)
    fs=[]
    for r in cut(list(csv.DictReader(open(EX+'3pl/outbound.csv')))):
        o=r['Order Reference'];k=o+'/'+r['Item Code'];L=["tpl/outbound_line",k]
        whole=["shopify/order_name",o] if o.startswith('#') else ["amazon/fba_shipment_id",o]
        fs+=[F(L,"tpl/outbound_line",k),F(L,"core/part_of",whole),F(L,"line/sku",["tpl/item_code",r['Item Code']])]
    write(fs,'3pl/outbound.csv',1)
