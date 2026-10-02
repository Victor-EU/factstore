import re,json,os,datetime as dt
S=os.path.dirname(os.path.abspath(__file__))
SUP={'MT':'NBBW','QS':'NBQS','HT':'SZHT','YD':'XMYD','TY':'HZTY','LX':'YWLX','MJ':'FSMJ','RF':'DGRF'}
num=lambda s:s.replace(',','')
def load_idx():
    return {os.path.basename(f)[:-4]:(f,h) for f,h,_ in json.load(open(S+'/pdfidx.json'))}
def txt(n): return open(f'{S}/txt/{n}.txt').read()
def parse_pi(n):
    t=txt(n); L=t.split('\n')
    d={'name_pdf':n,'name_cn':L[0],'name_caps':L[1],'address':L[2]}
    d['pi_no']=re.search(r'PI No\.: (\S+)',t).group(1)
    d['date']=re.search(r'Date: (\d{4}-\d\d-\d\d)',t).group(1)
    d['po']=re.search(r'Your PO: (PO-\d{4}-\d{4})',t).group(1)
    rows=[]
    for i,l in enumerate(L):
        m=re.match(r'^([\d,]+) ([\d,]+) (USD|RMB) ([\d.,]+) (USD|RMB) ([\d.,]+)$',l)
        if m:
            code=L[i-2].split(' ')[0]
            rows.append(dict(item=code,qty=int(num(m[1])),ctns=int(num(m[2])),cur=m[3],price=num(m[4]),amt=num(m[6])))
    d['rows']=rows
    d['total']=num(re.search(r'TOTAL (?:USD|RMB) ([\d.,]+)',t).group(1))
    d['incoterm']=re.search(r'Price term: (.*)',t).group(1).strip()
    d['payment']=re.search(r'Payment: (.*)',t).group(1).strip()
    d['etd_txt']=re.search(r'about (\w+ \d+, \d{4}) \(ETD\)',t).group(1)
    d['etd']=dt.datetime.strptime(d['etd_txt'],'%b %d, %Y').date().isoformat()
    m=re.search(r'Beneficiary: (.*)',t); d['beneficiary']=m.group(1).strip() if m else None
    d['cur']=rows[0]['cur']; d['sup']=SUP[n.replace('HT-PI','HT').split('-')[0].rstrip('0123456789') if False else re.match(r'[A-Z]+',n)[0]]
    return d
def parse_ci(n):
    t=txt(n); L=t.split('\n')
    d={'n':n}
    m=re.search(r'Invoice No\.: (\S+)\s+Date: (\d{4}-\d\d-\d\d)\s+Order: (PO-\d{4}-\d{4})',t); d['inv'],d['date'],d['po']=m.groups()
    m=re.search(r'From (\w+) to (\w+) by sea, (MV [\w ]+? \d+[A-Z])\s+Container: (\w+)\s+B/L: (\w+)',t)
    d['origin'],d['dest'],d['vessel'],d['container'],d['hbl']=m.groups()
    rows=[]
    for i,l in enumerate(L):
        m=re.match(r'^(\d{4}\.\d\d\.\d{4}) ([\d,]+) (?:USD|RMB) ([\d.,]+) (?:USD|RMB) ([\d.,]+)$',l)
        if m: rows.append(dict(item=L[i-2].split(' ')[0],hs=m[1],qty=int(num(m[2])),price=num(m[3])))
    d['rows']=rows
    pk={}
    for l in L:
        m=re.match(r'^(\d+)(?:-(\d+))? (\S+) (\d+) (\d+) ([\d,]+) ',l)
        if m: pk.setdefault(m[3],[]).append(dict(ctns=int(m[4]),pcs=int(num(m[6]))))
    d['pack']=pk
    return d
def parse_qc(n):
    t=txt(n); d={'n':n}
    d['report']=re.search(r'Report No\.: (\S+)',t).group(1)
    d['date']=re.search(r'Inspection date: (\S+)',t).group(1)
    d['po']=re.search(r'PO No\.: (\S+)',t).group(1)
    d['result']=re.search(r'Overall result: (\w+)',t).group(1)
    d['sample']=int(re.search(r'sample size (\d+)',t).group(1))
    d['agency']=t.split('\n')[0]
    d['supplier']=re.search(r'Supplier: (.*)',t).group(1)
    return d
if __name__=='__main__':
    idx=load_idx(); import collections
    pis=[];cis=[];qcs=[]
    for n in idx:
        if n.startswith('CI-PL'): cis.append(parse_ci(n))
        elif n.startswith('LCI'): qcs.append(parse_qc(n))
        else: pis.append(parse_pi(n))
    print(len(pis),len(cis),len(qcs))
    for p in pis:
        s=sum(float(r['amt']) for r in p['rows'])
        if abs(s-float(p['total']))>0.01 or not p['rows']: print('PI sum mismatch',p['pi_no'],s,p['total'])
        if not p['beneficiary']: print('no beneficiary',p['pi_no'])
    for c in cis:
        for r in c['rows']:
            if r['item'] not in c['pack'] : print('no pack',c['n'],r['item'])
        if sum(len(v) for v in c['pack'].values())!=len(c['rows']): print('pack rows',c['n'])
        if not c['rows']: print('no rows',c['n'])
    for q in qcs: print(q['report'],q['date'],q['po'],q['result'],q['sample'],q['agency'])
    names=collections.defaultdict(set)
    for p in pis: names[p['sup']].add((p['name_caps'],p['beneficiary'],p['name_cn'],p['address']))
    for k,v in names.items(): print(k,v)
    pay=collections.defaultdict(list)
    for p in sorted(pis,key=lambda p:p['date']): pay[p['sup']].append((p['date'],p['payment'],p['incoterm'],p['cur']))
    for k,v in pay.items(): print(k,sorted(set(x[1:] for x in v)))
