import re,glob,os,datetime as dt
from zoneinfo import ZoneInfo
from parse_email import emails
from parse_pdf import *
NY=ZoneInfo('America/New_York');LA=ZoneInfo('America/Los_Angeles');CN=ZoneInfo('Asia/Shanghai')
PORTTZ={'CNYTN':CN,'CNNGB':CN,'CNXMN':CN,'CNNSA':CN,'USNYC':NY,'USLAX':LA}
def mon(s):
    d,m,y=s.split();return dt.date(int(y),MONTHS[m],int(d))
def at_port(date,loc): return dt.datetime(date.year,date.month,date.day,tzinfo=PORTTZ[loc])
def fullpo(s):
    s=s.strip()
    m=re.fullmatch(r'(?i)PO[-# ]*(\d{4})-(\d{4})',s)
    if m: return f'PO-{m.group(1)}-{m.group(2)}'
    m=re.fullmatch(r'(?i)PO[-# ]*(\d{1,4})',s)
    n=int(m.group(1)); y=2025 if n>=143 else 2026
    return f'PO-{y}-{n:04d}'
SUP={'SHENZHEN HETAI':'SZHT','YIWU LANXIN':'YWLX','FOSHAN MINGJIA':'FSMJ','NINGBO MINGTU':'NBBW','NINGBO QISHENG':'NBQS','DONGGUAN RUIFENG':'DGRF','HANGZHOU TIANYI':'HZTY','XIAMEN YUANDA':'XMYD'}
def supcode(name):
    for k,v in SUP.items():
        if name.upper().startswith(k): return v
PIS={}
for f in H:
    if f.endswith('.pdf') and not f.startswith(('CI-PL','LCI')):
        d=parse_pi(f); d['file']=f; d['sup']=supcode(d['name']); PIS[d['po']]=d
PIBYNUM={d['pi']:d for d in PIS.values()}
def parse_booking(e):
    b=e['body'];g=lambda p:re.search(p,b).group(1).strip()
    so=g(r'SO: (\S+)')
    eq=g(r'Equipment: (.*)'); mode='LCL' if eq.startswith('LCL') else re.search(r'x(\d+(?:HQ|GP))',eq).group(1)
    pol=re.search(r'POL: .*?\((\w+)\)\s+POD: .*?\((\w+)\)',b)
    return dict(so=so,mode=mode,equip=eq,vessel=g(r'Vessel/Voyage: (.*)'),pol=pol.group(1),pod=pol.group(2),
      etd=at_port(mon(g(r'ETD: (.*)')),pol.group(1)),eta=at_port(mon(g(r'ETA: (.*)')),pol.group(2)),
      pos=[fullpo(x) for x in g(r'POs: (.*)').split(',')],shipper=g(r'Shipper\(s\): (.*)'))
def parse_prealert(e):
    b=e['body'];g=lambda p:re.search(p,b).group(1).strip()
    hbl=g(r'HBL: (\S+)'); cs=g(r'Container/Seal: (.*)').split(' / ')[0].strip()
    rows=[(fullpo(m.group(1)),m.group(2),int(m.group(3)),int(m.group(4))) for m in re.finditer(r'(?m)^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+([\d,]+) pcs',b) ] if False else \
         [(m.group(1),m.group(2),int(m.group(3)),int(m.group(4).replace(',',''))) for m in re.finditer(r'(?m)^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+([\d,]+) pcs',b)]
    m=re.search(r'ATD (\w+)\S*: (.*)',b)
    return dict(hbl=hbl,container=None if cs=='LCL' else cs,vessel=g(r'Vessel/Voyage: (.*)'),
       pol_name=m.group(1),atd=mon(m.group(2).strip()),eta_d=mon(g(r'ETA [^:]*: (.*)')),rows=rows,eta_name=re.search(r'ETA ([^:]*):',b).group(1))
if __name__=='__main__':
    es=emails()
    for e in es:
        s=e['subject']
        if s.startswith('Booking'): print('B',parse_booking(e)['so'],parse_booking(e)['pos'],parse_booking(e)['vessel'])
        elif s.startswith('Shipping'): p=parse_prealert(e); print('P',p['hbl'],p['container'],p['vessel'],p['pol_name'],p['eta_name'],sorted({r[0] for r in p['rows']}),len(p['rows']))
