import re,json,glob,os,hashlib
S=os.path.dirname(os.path.abspath(__file__))
EXP='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-h-ev4813q6/ingest/work/exports'
num=lambda s: s.replace(',','')
def parse_all():
    docs=[]
    for f in sorted(glob.glob(EXP+'/supplier_docs/*.pdf')):
        b=os.path.basename(f); t=open(f"{S}/txt/{b}.txt").read()
        h=hashlib.sha256(open(f,'rb').read()).hexdigest()
        d={'file':b,'hash':h,'url':'supplier_docs/'+b}
        if b.startswith('LCI-'):
            d['kind']='qc'
            g=lambda p: re.search(p,t).group(1).strip()
            d['report_no']=g(r'Report No\.: (\S+)'); d['date']=g(r'Inspection date: (\S+)')
            d['po']=g(r'PO No\.: (\S+)'); d['result']=g(r'Overall result: (\S+)')
            d['sample']=int(g(r'sample size (\d+)')); d['inspector']=t.split('\n')[0]
            d['supplier']=g(r'Supplier: (.*)')
        elif b.startswith('CI-PL_'):
            d['kind']='ci'
            m=re.search(r'Invoice No\.: (\S+)\s+Date: (\S+)\s+Order: (\S+)',t); d['inv'],d['date'],d['po']=m.groups()
            m=re.search(r'From (\w+) to (\w+) by sea, (.*?)\s+Container: (\S+)\s+B/L: (\S+)',t)
            d['origin'],d['dest'],d['vessel'],d['container'],d['hbl']=m.groups()
            rows=[]
            for m in re.finditer(r'^(\S+) .*\n.*\n(\d{4}\.\d\d\.\d{4}) ([\d,]+) (USD|RMB) ([\d,.]+) (USD|RMB) ([\d,.]+)$',t,re.M):
                rows.append(dict(item=m.group(1),hs=m.group(2),qty=int(num(m.group(3))),cur=m.group(4),price=num(m.group(5))))
            d['rows']=rows
            pl={}
            for m in re.finditer(r'^[\d-]+ (\S+) (\d+) (\d+) ([\d,]+) [\d,.]+ \S+ [\d.]+$',t,re.M):
                pl[m.group(1)]=dict(ctns=int(m.group(2)),pcs=int(num(m.group(4))))
            d['pl']=pl
            d['ntext_items']=len(re.findall(r'^HS Code|\d{4}\.\d\d\.\d{4}',t,re.M))
        else:
            d['kind']='pi'
            g=lambda p: re.search(p,t).group(1).strip()
            d['pi']=g(r'PI No\.: (\S+)'); d['date']=g(r'Date: (\d{4}-\d\d-\d\d)'); d['po']=g(r'Your PO: (PO-\d{4}-\d{4})')
            d['name_cn']=t.split('\n')[0]; d['name_caps']=t.split('\n')[1]
            d['address']=t.split('\n')[2]
            d['beneficiary']=g(r'Beneficiary: (.*)')
            d['incoterm']=g(r'Price term: (.*)'); d['payment']=g(r'Payment: (.*)')
            d['etd']=g(r'about (\w+ \d\d, \d{4}) \(ETD\)')
            rows=[]
            for m in re.finditer(r'^(\S+) .*\n.*\n([\d,]+) (\d+) (USD|RMB) ([\d,.]+) (USD|RMB) ([\d,.]+)$',t,re.M):
                rows.append(dict(item=m.group(1),qty=int(num(m.group(2))),ctns=int(m.group(3)),cur=m.group(4),price=num(m.group(5))))
            d['rows']=rows
            d['ncodes']=len(re.findall(r'^Item No\.',t,re.M))
        docs.append(d)
    return docs
if __name__=='__main__':
    D=parse_all(); json.dump(D,open(S+'/pdfs.json','w'),indent=1)
    from collections import Counter
    print(Counter(d['kind'] for d in D))
    for d in D:
        if d['kind']=='pi':
            t=open(f"{S}/txt/{d['file']}.txt").read()
            n=len(re.findall(r'^TOTAL',t,re.M)); 
            lines=len(re.findall(r'(USD|RMB) [\d,.]+ (USD|RMB) [\d,.]+$',t,re.M))
            if lines!=len(d['rows']): print('PI rows mismatch',d['file'],lines,len(d['rows']))
        if d['kind']=='ci':
            t=open(f"{S}/txt/{d['file']}.txt").read()
            lines=len(re.findall(r'^\d{4}\.\d\d\.\d{4}',t,re.M))
            if lines!=len(d['rows']) or len(d['pl'])!=len(d['rows']): print('CI mismatch',d['file'],lines,len(d['rows']),len(d['pl']))
