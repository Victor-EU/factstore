from common import *
import sys
live = len(sys.argv)>1 and sys.argv[1]=='live'
hubs=json.load(open(S+'/hubs.json')); item2sku={h['item']:c for c,h in hubs.items()}
SK=lambda c:["sku/code",c]
known_nonreceipt=set()
# known POs: any PO-YYYY-NNNN seen in docs, chats, email, receipts
known=set()
for p in glob.glob(S+'/txt/*.txt')+glob.glob(X+'/wechat/*.txt')+[X+'/email/ops_inbox.mbox']:
    known|=set(re.findall(r'PO-20\d\d-\d{4}',open(p,errors='ignore').read()))
known_nonreceipt=set(known)
known|=set(re.findall(r'PO-20\d\d-\d{4}',open(X+'/3pl/receipts.csv').read()))
print('known POs',len(known),sorted(known)[:3],sorted(known)[-3:])
# receipts
rc=list(csv.DictReader(open(X+'/3pl/receipts.csv')))
byr=collections.defaultdict(list)
for r in rc: byr[r['Receipt #']].append(r)
F=[];G=[];badref=0;nopo=0;hbl=0
for k,rows in byr.items():
    pos={r['Reference'] for r in rows}; cs={r['Container #'] for r in rows}
    assert len(pos)==1 and len(cs)==1,(k,pos,cs)
    e=["tpl/receipt_no",k]; F.append({"e":e,"a":"tpl/receipt_no","v":k})
    po=pos.pop()
    if po:
        ps=[x.strip() for x in po.split('/')]
        for p in ps:
            assert re.fullmatch(r'PO-20\d\d-\d{4}',p),po
            F.append({"e":e,"a":"record/po","v":["po/number",p]})
    else: nopo+=1
    c=cs.pop()
    if c.startswith('PBLHB'): F.append({"e":e,"a":"record/shipment","v":["shipment/hbl",c]}); hbl+=1
for r in rc:
    key=r['Receipt #']+'/'+r['Item Code']; e=["tpl/receipt_line_key",key]
    G+=[{"e":e,"a":"tpl/receipt_line_key","v":key},{"e":e,"a":"core/part_of","v":["tpl/receipt_no",r['Receipt #']]},{"e":e,"a":"line/sku","v":SK(item2sku[r['Item Code']])}]
print('receipt po not in docs/chats:',sorted({f['v'][1] for f in F if f['a']=='record/po'}-{p for q in [] for p in q}-known_nonreceipt))
print('receipts',len(byr),'lines',len(rc),'no po',nopo,'hbl',hbl)
# outbound
ob=list(csv.DictReader(open(X+'/3pl/outbound.csv')))
O=[]
for r in ob:
    ref=r['Order Reference']; key=ref+'/'+r['Item Code']; e=["tpl/outbound_line_key",key]
    tgt=["amazon/inbound_shipment_id",ref] if ref.startswith('FBA') else ["shopify/order_name",ref]
    O+=[{"e":e,"a":"tpl/outbound_line_key","v":key},{"e":e,"a":"outbound_line/for","v":tgt},{"e":e,"a":"line/sku","v":SK(item2sku[r['Item Code']])}]
print('outbound',len(ob))
# quickbooks bills
qb=list(csv.DictReader(open(X+'/quickbooks/transaction_list_by_vendor.csv')))
vend={r['Vendor'] for r in csv.DictReader(open(X+'/quickbooks/vendors.csv'))}
B=[];seen=set();unres=collections.Counter();npo=0;nsh=0
for r in qb:
    if r['Transaction type']!='Bill': continue
    assert r['Num'] and r['Vendor'] in vend
    key=r['Vendor']+':'+r['Num']; e=["quickbooks/bill_key",key]
    memo=r['Memo/Description']
    pos=set(re.findall(r'PO-20\d\d-\d{4}',memo))|{x.replace('#','-') for x in []}
    for m in re.findall(r'(?i)\bPO[#\s-]*(\d{4}-\d{4})',memo): pos.add('PO-'+m)
    for m in re.findall(r'(?i)\bPO[#\s]*(\d{3,4})\b(?!-)',memo):
        n=int(m); cand='PO-%d-%04d'%(2025 if n>=100 else 2026,n)
        if cand in known: pos.add(cand)
        else: unres[memo]+=1
    pos={p for p in pos if p in known}
    shp=set(re.findall(r'PBLHB\d{7}',memo))
    if key in seen:
        B_pos=[]  # additional lines of same bill: same facts, skip duplicates by merging below
    seen.add(key)
    B+=[{"e":e,"a":"quickbooks/bill_key","v":key},{"e":e,"a":"bill/vendor","v":["quickbooks/vendor",r['Vendor']]}]
    B+=[{"e":e,"a":"record/po","v":["po/number",p]} for p in sorted(pos)]
    B+=[{"e":e,"a":"record/shipment","v":["shipment/hbl",h]} for h in sorted(shp)]
    npo+=len(pos); nsh+=len(shp)
print('bills',len(seen),'po refs',npo,'shipment refs',nsh,'unresolved',list(unres)[:10])
if live:
    write(F,[X+'/3pl/receipts.csv'],label='receipts')
    write(G,[X+'/3pl/receipts.csv'],label='receipt lines')
    write(O,[X+'/3pl/outbound.csv'],label='outbound lines')
    write(B,[X+'/quickbooks/transaction_list_by_vendor.csv'],label='bills')
