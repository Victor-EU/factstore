import re,json,sys,datetime as dt,collections
from zoneinfo import ZoneInfo
import pdfs,chats,emails
UTC=dt.timezone.utc
TZ={'CN':ZoneInfo('Asia/Shanghai'),'USNYC':ZoneInfo('America/New_York'),'USLAX':ZoneInfo('America/Los_Angeles')}
def port_tz(code): return TZ['CN'] if code.startswith('CN') else TZ[code]
def inst(d,code):  # date at 00:00 local to port -> ISO with offset
    return dt.datetime(d.year,d.month,d.day,tzinfo=port_tz(code)).isoformat()
RANK={'draft':0,'sent':1,'confirmed':2,'in_production':3,'ready':4,'shipped':5,'received':6}
PORT={'Ningbo':'CNNGB','Yantian':'CNYTN','Xiamen':'CNXMN','Nansha':'CNNSA','Foshan':'CNFOS'}
SKU=json.load(open(pdfs.S+'/skus.json'))  # code -> hs
def d_(s,f='%d %b %Y'): return dt.datetime.strptime(s,f).date()
def norm_po(s):
    s=s.strip()
    m=re.match(r'(?i)PO[#\- ]*(\d{4})-(\d{4})$',s)
    if m: return f'PO-{m[1]}-{m[2]}',True
    m=re.match(r'(?i)PO[#\- ]*(\d+)$',s)
    n=int(m[1]); y=2025 if n>=143 else 2026
    return f'PO-{y}-{n:04d}',False   # loosely named: year inferred

events=[]   # (utc, seq, kind, payload)
def add(ts,kind,p):
    if ts.tzinfo is None: raise Exception('naive')
    events.append((ts.astimezone(UTC),len(events),kind,p))
idx=pdfs.load_idx()
PI={};PIBYNO={}
for n,(f,h) in idx.items():
    url=f.replace('\\','/')
    doc=dict(hash=h,url=url)
    if n.startswith('CI-PL'):
        c=pdfs.parse_ci(n); c['doc']=doc
        add(dt.datetime.fromisoformat(c['date']).replace(tzinfo=TZ['CN'],hour=12),'ci',c)
    elif n.startswith('LCI'):
        q=pdfs.parse_qc(n); q['doc']=doc
        add(dt.datetime.fromisoformat(q['date']).replace(tzinfo=TZ['CN'],hour=12),'qc',q)
    else:
        p=pdfs.parse_pi(n); p['doc']=doc; PI[p['po']]=p; PIBYNO[p['pi_no']]=p
        add(dt.datetime.fromisoformat(p['date']).replace(tzinfo=TZ['CN'],hour=8),'pi',p)
# ---------- emails
BOOK=[]
for e in emails.load():
    raw=e['raw']
    if raw.endswith(b'\n\n'): raw=raw[:-1]   # drop the mbox separator line
    import hashlib
    doc=dict(hash=hashlib.sha256(raw).hexdigest(),url='mid:'+e['mid'])
    s=e['subj']; b=e['body']; d=dict(doc=doc,subj=s,body=b,ts=e['date'])
    g=lambda pat:(re.search(pat,b,re.M) or [None,None])[1]
    if s.startswith('Booking Confirmation'):
        d['kind']='booking'; d['so']=g(r'^SO: (\S+)')
        eq=g(r'^Equipment: (.*)$'); d['mode']='LCL' if eq.startswith('LCL') else re.search(r'x(\w+)',eq)[1]
        d['vessel']=g(r'^Vessel/Voyage: (.*)$').strip()
        m=re.search(r'POL: .*\((\w+)\)\s+POD: .*\((\w+)\)',b); d['pol'],d['pod']=m.groups()
        d['etd']=d_(g(r'^ETD: (.*)$')); d['eta']=d_(g(r'^ETA: (.*)$'))
        d['pos']=[norm_po(x) for x in g(r'^POs: (.*)$').split(',')]
    elif s.startswith('RE: Booking'):
        d['kind']='roll'; d['so']=g(r'rolled SO (\S+)')
        m=re.search(r'New ETD (\d+ \w+ \d{4}), ETA (\d+ \w+ \d{4})',b); d['etd']=d_(m[1]); d['eta']=d_(m[2])
    elif s.startswith('Shipping Advice'):
        d['kind']='prealert'; d['hbl']=g(r'^HBL: (\S+)')
        cs=g(r'^Container/Seal: (.*)$'); d['container']=cs.split(' / ')[0].strip()
        d['vessel']=g(r'^Vessel/Voyage: (.*)$').strip()
        m=re.search(r'ATD (\w+): (.*)',b); d['atd']=d_(m[2]); d['pol_name']=m[1]
        d['eta']=d_(g(r'^ETA New York/Newark: (.*)$') or g(r'^ETA [\w /]+: (.*)$'))
        d['lines']=[(m[1],m[2],int(m[3]),int(m[4])) for m in re.finditer(r'(?m)^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs',b)]
    elif s.startswith('ETA update'):
        d['kind']='eta'; d['hbl']=g(r'for HBL (\S+)'); d['eta']=d_(g(r'revised ETA (\d+ \w+ \d{4})'))
    elif s.startswith('Arrival Notice'):
        d['kind']='arrival'; d['hbl']=g(r'Shipment HBL (\S+)'); d['arr']=d_(re.search(r'arriving [\w/ ]+ on (\d+ \w+ \d{4})',b)[1])
    elif s.startswith('Entry Summary'):
        d['kind']='entry'; m=re.search(r'Entry (\S+) filed for (\S+)\.',b); d['entry'],d['ref']=m.groups()
        val=lambda k:re.search(k+r': USD ([\d,]+\.\d\d)',b)[1].replace(',','')
        d['value']=val('Entered value'); d['hts']=val(r'Duty \(HTS\)'); d['s301']=val('Section 301'); d['add']=val('Additional duties')
        d['mpf']=val('MPF'); d['hmf']=val('HMF'); d['total']=val('Total duties and fees')
    elif s.startswith('Receipt complete'):
        d['kind']='receipt'; m=re.search(r'Receiving complete for (\S+) under (\S+)',b); d['ref'],d['rcv']=m.groups()
    else: raise Exception(s)
    add(e['date'],'mail',d)
# ---------- chats
CH=chats.load()
for m in CH: add(m['ts'],'chat',m)
events.sort(key=lambda x:(x[0],x[1]))
