import json,re,glob,os
idx=json.load(open('idx.json'))
docs=[]
num=lambda s:s.replace(',','')
for f,h in idx:
    t=open(f'txt/{f}.txt').read()
    d={'file':f,'hash':h,'text_len':len(t)}
    L=t.split('\n')
    if 'PROFORMA INVOICE' in t:
        d['kind']='PI'
        d['supplier_en']=L[1].strip()
        d['pi']=re.search(r'PI No\.: (\S+)',t).group(1)
        d['date']=re.search(r'Date: (\d{4}-\d\d-\d\d)',t).group(1)
        d['po']=re.search(r'Your PO: (PO-\d{4}-\d{4})',t).group(1)
        items=[]
        for i,l in enumerate(L):
            m=re.match(r'^([\d,]+) ([\d,]+) (USD|RMB) ([\d,.]+) (?:USD|RMB) ([\d,.]+)$',l)
            if m:
                code=L[i-2].split(' ')[0]
                items.append(dict(code=code,qty=num(m[1]),ctns=num(m[2]),cur=m[3],price=m[4],amt=num(m[5]),desc=L[i-2]))
        d['items']=items
        m=re.search(r'Delivery: about (\w+ \d+, \d{4}) \(ETD\)',t)
        d['etd']=m and m[1]
        d['incoterm']=re.search(r'Price term: (.+)',t).group(1).strip()
        d['pay']=re.search(r'Payment: (.+)',t).group(1).strip()
        d['total']=re.search(r'^TOTAL (?:USD|RMB) ([\d,.]+)',t,re.M).group(1)
        d['addr']=L[2].strip(); d['cn']=L[0].strip()
    elif 'COMMERCIAL INVOICE' in t:
        d['kind']='CI'
        d['supplier_en']=L[1].strip()
        m=re.search(r'Invoice No\.: (\S+)\s+Date: (\S+)\s+Order: (PO-\d{4}-\d{4})',t)
        d['inv'],d['date'],d['po']=m.groups()
        m=re.search(r'From (\w+) to (\w+) by sea, (.+?)\s+Container: (\S+)\s+B/L: (\S+)',t)
        d['origin'],d['dest'],d['vessel'],d['container'],d['hbl']=m.groups()
        rows=[]
        for i,l in enumerate(L):
            m=re.match(r'^(\d{4}\.\d\d\.\d{4}) ([\d,]+) (USD|RMB) ([\d,.]+) (?:USD|RMB) ([\d,.]+)$',l)
            if m: rows.append(dict(code=L[i-2].split(' ')[0],hs=m[1],qty=num(m[2]),price=m[4]))
        d['rows']=rows
        pl={}
        for l in L:
            m=re.match(r'^[\d-]+ (\S+) (\d+) (\d+) ([\d,]+) [\d,.]+ \S+ [\d.]+$',l)
            if m: pl[m[1]]=dict(ctns=m[2],pcs=num(m[4]))
        d['pl']=pl
        d['ctotal']=re.search(r'TOTAL: (\d+) CTNS',t).group(1)
    elif 'Inspection Report' in t:
        d['kind']='QC'
        d['report']=re.search(r'Report No\.: (\S+)',t).group(1)
        d['date']=re.search(r'Inspection date: (\S+)',t).group(1)
        d['po']=re.search(r'PO No\.: (\S+)',t).group(1)
        d['result']=re.search(r'Overall result: (\w+)',t).group(1)
        d['sample']=re.search(r'sample size (\d+)',t).group(1)
        d['supplier_en']=re.search(r'Supplier: (.+)',t).group(1)
        d['agency']=L[0].strip()
    else: d['kind']='?'
    docs.append(d)
json.dump(docs,open('docs.json','w'),indent=1)
from collections import Counter
print(Counter(d['kind'] for d in docs))
for d in docs:
    if d['kind']=='PI':
        s=sum(float(i['amt']) for i in d['items'])
        if abs(s-float(num(d['total'])))>0.01 or not d['etd'] or not d['items']: print('PI?',d['file'],s,d['total'],d['etd'])
    if d['kind']=='CI':
        if not d['rows'] or set(r['code'] for r in d['rows'])!=set(d['pl']): print('CI?',d['file'],len(d['rows']),len(d['pl']))
        for r in d['rows']:
            if d['pl'].get(r['code'],{}).get('pcs')!=r['qty']: print('CI qty',d['file'],r)
