import re,json,glob,os,datetime as dt
S=os.path.dirname(os.path.abspath(__file__))
H={os.path.basename(f):h for f,h in json.load(open(S+'/hashes.json'))}
def txt(name): return open(f'{S}/txt/{name}.txt').read()
MONTHS={m:i for i,m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(),1)}
def parse_pi(name):
    t=txt(name); L=t.split('\n')
    d={}
    d['name_cn']=L[0].strip(); d['name']=L[1].strip(); d['address']=L[2].strip()
    d['pi']=re.search(r'PI No\.: (\S+)',t).group(1)
    d['date']=re.search(r'Date: (\d{4}-\d\d-\d\d)',t).group(1)
    d['po']=re.search(r'Your PO: (\S+?)(?:Attn|\s|$)',t).group(1)
    m=re.search(r'Delivery: about (\w{3}) (\d+), (\d{4})',t)
    d['etd']=dt.date(int(m.group(3)),MONTHS[m.group(1)],int(m.group(2))).isoformat()
    d['incoterm']=re.search(r'Price term: (.*)',t).group(1).strip()
    d['payment']=re.search(r'Payment: (.*)',t).group(1).strip()
    items=[]
    for m in re.finditer(r'(?m)^(\S+) [^\n]*\n[^\n]*\n([\d,]+) (\d+) (USD|RMB) ([\d,.]+) (?:USD|RMB) ([\d,.]+)$',t):
        items.append(dict(item=m.group(1),qty=int(m.group(2).replace(',','')),ctns=int(m.group(3)),cur=m.group(4),price=m.group(5),amt=m.group(6)))
    d['items']=items
    d['total']=re.search(r'TOTAL (?:USD|RMB) ([\d,.]+)',t).group(1)
    return d
def parse_qc(name):
    t=txt(name)
    g=lambda p:re.search(p,t).group(1)
    return dict(report=g(r'Report No\.: (\S+)'),date=g(r'Inspection date: (\S+)'),po=g(r'PO No\.: (.+)'),
      sample=int(g(r'sample size (\d+)')),result=g(r'Overall result: (\w+)'),agency=t.split('\n')[0].strip(),
      supplier=g(r'Supplier: (.*)'))
if __name__=='__main__':
    for f in sorted(H):
        if f.startswith('CI-PL') : continue
        if f.startswith('LCI'):
            q=parse_qc(f); print(f,q['date'],q['po'],q['result'],q['sample'],q['agency']);continue
        d=parse_pi(f)
        chk=sum(round(float(i['price'])*i['qty'],2) for i in d['items'])
        ok = abs(chk-float(d['total'].replace(',','')))<0.01
        print(f,d['date'],d['po'],d['etd'],d['name'][:22],len(d['items']),d['items'][0]['cur'],d['incoterm'],'|',d['payment'],'OK' if ok else 'TOTAL MISMATCH')
