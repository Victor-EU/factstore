import re,glob,os,hashlib,json
ROOT='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-f-pyk9rvda/ingest/work/exports'
TXT='/private/tmp/claude-501/-private-var-folders-qj-j67my3-j6bzb4y5t82bvmkfh0000gn-T-m5-f-pyk9rvda-ingest-work/5bb7f744-9da6-4c2b-b2d6-138a5674aac4/scratchpad/txt'
SUP={'NBBW':'Mingtu','NBQS':'Qisheng','SZHT':'Hetai','YWLX':'Lanxin','FSMJ':'Mingjia','DGRF':'Ruifeng','HZTY':'Tianyi','XMYD':'Yuanda'}
def num(s): return s.replace(',','')
def parse_pi(t,code):
    d={}
    d['name_en']=re.search(r'\n(.+CO\., LTD\.)\n',t).group(1)
    d['name_cn']=t.split('\n')[0]
    d['address']=t.split('\n')[2]
    d['pi']=re.search(r'PI No\.: (\S+)',t).group(1)
    d['date']=re.search(r'Date: (\d{4}-\d\d-\d\d)',t).group(1)
    d['po']=re.search(r'Your PO: (PO-\d{4}-\d{4})',t).group(1)
    d['term']=re.search(r'Price term: (\w+) (\w+)',t).groups()
    d['pay']=re.search(r'Payment: (.+)',t).group(1).strip()
    d['etd']=re.search(r'about (\w+ \d\d, \d{4}) \(ETD\)',t).group(1)
    items=[]
    for m in re.finditer(r'(?m)^(\S+) (.+)\n.*\n([\d,]+) ([\d,]+) (USD|RMB) ([\d,.]+) (?:USD|RMB) ([\d,.]+)$',t):
        items.append(dict(item=m.group(1),qty=int(num(m.group(3))),ctns=int(m.group(4)),cur=m.group(5),price=m.group(6)))
    d['items']=items
    d['total']=re.search(r'TOTAL (USD|RMB) ([\d,.]+)',t).groups()
    return d
def parse_ci(t):
    d={}
    d['inv']=re.search(r'Invoice No\.: (\S+)\s+Date: (\d{4}-\d\d-\d\d)\s+Order: (\S+)',t).groups()
    m=re.search(r'From (\w+) to (\w+) by sea, (.+?)\s+Container: (\S+)\s+B/L: (\S+)',t)
    d['from'],d['to'],d['vessel'],d['cont'],d['bl']=m.groups()
    items=[]
    for m in re.finditer(r'(?m)^(\S+) (.+)\n.*\n(\d{4}\.\d\d\.\d{4}) ([\d,]+) (USD|RMB) ([\d.,]+) (?:USD|RMB) ([\d,.]+)$',t):
        items.append(dict(item=m.group(1),hs=m.group(3),qty=int(num(m.group(4)))))
    d['items']=items
    pl={}
    for m in re.finditer(r'(?m)^(\d+-\d+|\d+) (\S+) (\d+) (\d+) ([\d,]+) ([\d,.]+) ',t):
        pl[m.group(2)]=pl.get(m.group(2),0)+int(m.group(3))
    d['ctns']=pl
    return d
def parse_qc(t):
    g=lambda p:re.search(p,t).group(1)
    return dict(report=g(r'Report No\.: (\S+)'),date=g(r'Inspection date: (\S+)'),agency=t.split('\n')[0],po=g(r'PO No\.: (\S+)'),sample=int(g(r'sample size (\d+)')),result=g(r'Overall result: (\w+)'))
def sha(p): return hashlib.sha256(open(p,'rb').read()).hexdigest()
def load():
    out=[]
    for f in sorted(glob.glob(ROOT+'/supplier_docs/*.pdf')):
        b=os.path.basename(f); t=open(f'{TXT}/{b}.txt').read()
        rec=dict(file=b,url='supplier_docs/'+b,hash=sha(f))
        if b.startswith('CI-PL_'): rec['kind']='ci'; rec.update(parse_ci(t)); rec['date']=rec['inv'][1]
        elif b.startswith('LCI'): rec['kind']='qc'; rec.update(parse_qc(t))
        else: rec['kind']='pi'; rec.update(parse_pi(t,b))
        out.append(rec)
    return out
if __name__=='__main__':
    L=load(); json.dump(L,open('pdfs.json','w'),ensure_ascii=False,indent=0)
    from collections import Counter
    print(Counter(r['kind'] for r in L))
    for r in L:
        if r['kind']=='pi':
            tot=sum(float(num(i['price']))*i['qty'] for i in r['items'])
            print(r['file'],r['po'],r['date'],r['etd'],r['term'],len(r['items']),r['total'],round(tot,2),r['pay'][:30])
