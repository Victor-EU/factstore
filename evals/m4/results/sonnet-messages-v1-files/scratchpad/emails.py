import json,re,store
from datetime import datetime
from zoneinfo import ZoneInfo
D=store.load()
docs=[d for d in json.load(open('docs.json')) if d['kind']=='email']
docs.sort(key=lambda d:d['utc'])
TZ={'CN':ZoneInfo('Asia/Shanghai'),'USNYC':ZoneInfo('America/New_York'),'USLAX':ZoneInfo('America/Los_Angeles')}
def inst(dstr,port):
    z=TZ['CN'] if port.startswith('CN') else TZ[port]
    return datetime.strptime(dstr,'%d %b %Y').replace(tzinfo=z).isoformat()
poset=set(D['po'])
def po_of(tok):
    t=re.sub(r'(?i)^po[#\s-]*','',tok.strip())
    if re.fullmatch(r'\d{4}-\d{4}',t): return 'PO-'+t
    n=int(re.sub(r'\D','',t))
    c=[p for p in poset if int(p[-4:])==n and (len(re.sub(r'\D','',t))<=3 or p.startswith('PO-2025') and n>=143)]
    c=[p for p in poset if int(p[-4:])==n]
    return c[0] if len(c)==1 else None
loc={'New York/Newark':'USNYC','Los Angeles':'USLAX'}
shipbyvessel={s['vessel']:s for s in D['ship'].values()}
shipbycont={s['cont']:s for s in D['ship'].values() if s['cont']}
shiplines={}
for l in D['lines']: shiplines.setdefault(l[0],[]).append(l)
events=[];issues=[]
for d in docs:
    t=d['text'];s=d['subject']
    ev=dict(doc=d,facts=[],conf='1',notes=[])
    def F(sub,a,v): ev['facts'].append((sub,a,v))
    if s.startswith('Booking Confirmation') or ('ROLLED' in s):
        so=re.search(r'SO (PB\w+)',s).group(1)
        if 'ROLLED' in s:
            m=re.search(r'New ETD (\d+ \w+ \d+), ETA (\d+ \w+ \d+)',t)
            ev.update(kind='roll',so=so,etd=m.group(1),eta=m.group(2))
        else:
            g=lambda k:re.search(k+r': (.*)',t).group(1).strip()
            eq=g('Equipment'); mode='LCL' if eq.startswith('LCL') else re.search(r'(40HQ|20GP)',eq).group(1)
            pol=re.search(r'\((\w{5})\)\s+POD: .*\((\w{5})\)',t)
            pos=[x for x in g('POs').split(', ')]
            ev.update(kind='booking',so=so,mode=mode,vessel=g('Vessel/Voyage'),o=pol.group(1),d=pol.group(2),etd=g('ETD'),eta=g('ETA'),pos=[po_of(x) for x in pos],rawpos=pos)
    elif s.startswith('Shipping Advice'):
        g=lambda k:re.search(k+r': (.*)',t).group(1).strip()
        cont,seal=g('Container/Seal').split(' / ')
        rows=re.findall(r'^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs',t,re.M)
        atd=re.search(r'ATD \w+: (.*)',t).group(1)
        eta=re.search(r'ETA [\w/ ]+: (.*)',t).group(1)
        ev.update(kind='prealert',hbl=g('HBL'),cont=None if cont=='LCL' else cont,vessel=g('Vessel/Voyage'),atd=atd,eta=eta,rows=rows)
    elif s.startswith('ETA update'):
        m=re.search(r'revised ETA (\d+ \w+ \d+) for HBL (\w+)',t); ev.update(kind='eta',eta=m.group(1),hbl=m.group(2))
    elif s.startswith('Arrival Notice'):
        m=re.search(r'HBL (\w+) \((\w+)\) on (MV [\w ]+) is arriving ([\w/ ]+?) on (\d+ \w+ \d+)',t)
        ev.update(kind='arrival',hbl=m.group(1),vessel=m.group(3),port=loc[m.group(4)],date=m.group(5))
    elif s.startswith('Entry Summary'):
        v=lambda k:float(re.search(k+r': USD ([\d,\.]+)',t).group(1).replace(',',''))
        ev.update(kind='entry',entry=re.search(r'Entry (\S+) filed',t).group(1),ref=s.split(' - ')[-1],val=v('Entered value'),
          duty=round(v(r'Duty \(HTS\)')+v('Section 301')+v('Additional duties'),2),fees=round(v('MPF')+v('HMF'),2),total=v('Total duties and fees'))
    elif s.startswith('Receipt complete'):
        ev.update(kind='receipt',ref=s.split(' - ')[-1],rcv=s.split()[2])
    else: issues.append(('unknown',s)); continue
    events.append(ev)
json.dump([{k:v for k,v in e.items() if k!='facts'} for e in events],open('email_events.json','w'),default=str,indent=0)
if __name__=='__main__':
    import collections
    print(collections.Counter(e['kind'] for e in events),issues)
    for e in events:
        if e['kind']=='entry' and abs(e['duty']+e['fees']-e['total'])>0.011: print('TOTAL MISMATCH',e['entry'],e['duty'],e['fees'],e['total'])
        if e['kind']=='booking' and None in e['pos']: print('unresolved PO',e['so'],e['rawpos'])
