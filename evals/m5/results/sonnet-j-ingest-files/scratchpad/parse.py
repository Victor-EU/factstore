import re,glob,os,hashlib,email,json
from datetime import datetime,timedelta,timezone
EX="/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-j-vps9guuv/ingest/work/exports"
S=os.path.dirname(os.path.abspath(__file__))
def sha(b): return hashlib.sha256(b).hexdigest()
def num(s): return s.replace(',','')
CODE={'深圳市和泰电器':'SZHT','义乌市蓝欣':'YWLX','佛山市明嘉':'FSMJ','杭州天艺':'HZTY','厦门远达':'XMYD','宁波启盛':'NBQS','宁波明途':'NBBW','东莞':'DGRF'}
def supcode(cn):
    for k,v in CODE.items():
        if cn.startswith(k): return v
    raise Exception(cn)
def pdftext(name): 
    t=open(f"{S}/txt/{name}.txt").read(); h,_,t=t.partition("\n"); return h[5:],t
def parse_pi(name):
    h,t=pdftext(name); L=t.split("\n")
    d=dict(hash=h,url="supplier_docs/"+name)
    d['name_cn']=L[0]; d['name']=None; d['addr']=L[2]; d['sup']=supcode(L[0])
    m=re.search(r'PI No\.: (\S+)',t); d['pi']=m.group(1)
    d['date']=re.search(r'Date: (\d{4}-\d\d-\d\d)',t).group(1)
    d['po']=re.search(r'Your PO: (PO-\d{4}-\d{4})',t).group(1)
    d['incoterm']=re.search(r'Price term: (.+)',t).group(1).strip()
    d['pay']=re.search(r'Payment: (.+)',t).group(1).strip()
    d['etd']=datetime.strptime(re.search(r'about (\w+ \d+, \d{4}) \(ETD\)',t).group(1),'%b %d, %Y').date().isoformat()
    d['bene']=re.search(r'Beneficiary: (.+)',t).group(1).strip()
    rows=[]
    for m in re.finditer(r'^(\S+) .*\n.*\n([\d,]+) (\d+) (USD|RMB) ([\d,\.]+) (?:USD|RMB) ([\d,\.]+)$',t,re.M):
        rows.append(dict(item=m.group(1),qty=num(m.group(2)),ctns=m.group(3),cur=m.group(4),price=num(m.group(5))))
    d['rows']=rows; d['cur']={'RMB':'CNY','USD':'USD'}[rows[0]['cur']]
    tot=re.search(r'^TOTAL (?:USD|RMB) ([\d,\.]+)',t,re.M)
    assert abs(sum(float(r['qty'])*float(r['price']) for r in rows)-float(num(tot.group(1))))<0.01,name
    d['port']={'Yantian':'CNYTN','Ningbo':'CNNGB','Xiamen':'CNXMN','Nansha':'CNNSA'}[d['incoterm'].split()[-1]]
    return d
def parse_ci(name):
    h,t=pdftext(name); d=dict(hash=h,url="supplier_docs/"+name)
    d['sup']=supcode(t.split("\n")[0])
    m=re.search(r'Invoice No\.: (\S+)\s+Date: (\S+)\s+Order: (PO-\d{4}-\d{4})',t); d['inv'],d['date'],d['po']=m.groups()
    m=re.search(r'From (\w+) to (\w+) by sea, (.+?)\s+Container: (\S+)\s+B/L: (\S+)',t); d['orig'],d['dest'],d['vessel'],d['cont'],d['hbl']=m.groups()
    rows=[]
    ci=t.split('PACKING LIST')[0]
    for m in re.finditer(r'^(\S+) .*\n.*\n(\d{4}\.\d\d\.\d{4}) ([\d,]+) (USD|RMB) ([\d,\.]+) (?:USD|RMB) ([\d,\.]+)$',ci,re.M):
        rows.append(dict(item=m.group(1),hs=m.group(2),qty=num(m.group(3))))
    pl=t.split('PACKING LIST')[1]; ct={}
    for m in re.finditer(r'^[\d\-]+ (\S+) (\d+) (\d+) ([\d,]+) ',pl,re.M): ct[m.group(1)]=(m.group(2),num(m.group(4)))
    for r in rows:
        r['ctns']=ct[r['item']][0]; assert ct[r['item']][1]==r['qty'],(name,r)
    assert len(rows)==len(ct),name
    d['rows']=rows; return d
def parse_qc(name):
    h,t=pdftext(name); d=dict(hash=h,url="supplier_docs/"+name)
    d['no']=re.search(r'Report No\.: (\S+)',t).group(1)
    d['date']=re.search(r'Inspection date: (\S+)',t).group(1)
    d['po']=re.search(r'PO No\.: (\S+)',t).group(1)
    d['result']=re.search(r'Overall result: (\w+)',t).group(1)
    d['n']=re.search(r'sample size (\d+)',t).group(1)
    d['agency']=t.split("\n")[0]
    return d
if __name__=="__main__":
    for f in sorted(os.listdir(EX+"/supplier_docs")):
        try:
            if f.startswith('CI-PL'): d=parse_ci(f); print(f,d['po'],d['date'],d['hbl'],d['cont'],d['vessel'],d['orig'],d['dest'],len(d['rows']))
            elif f.startswith('LCI'): d=parse_qc(f); print(f,d['po'],d['date'],d['result'],d['n'],d['agency'])
            else: d=parse_pi(f); print(f,d['po'],d['date'],d['etd'],d['cur'],len(d['rows']))
        except Exception as e: print("FAIL",f,repr(e))
