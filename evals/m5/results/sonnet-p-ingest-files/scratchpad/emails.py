from parse import *
MON={m:i for i,m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(),1)}
def dmy(s):
    m=re.match(r'(\d+) (\w{3}) (\d{4})',s); return f"{m.group(3)}-{MON[m.group(2)]:02d}-{int(m.group(1)):02d}"
ev=[]
for e in emails:
    s=e['subject']; b=e['body']; r=dict(e=e,dt=e['dt'])
    if s.startswith('Booking Confirmation') and 'ROLLED' not in s:
        r['kind']='booking'
        r['so']=re.search(r'SO: (\S+)',b).group(1)
        m=re.search(r'Equipment: (\S+)',b); r['mode']=m.group(1)
        r['vessel']=re.search(r'Vessel/Voyage: (.+)',b).group(1).strip()
        m=re.search(r'POL: .*?\((\w+)\)\s+POD: .*?\((\w+)\)',b); r['pol'],r['pod']=m.groups()
        r['etd']=dmy(re.search(r'ETD: (.+)',b).group(1)); r['eta']=dmy(re.search(r'ETA: (.+)',b).group(1))
        r['pos']=['PO-'+x for x in re.findall(r'PO#(\d{4}-\d{4})',re.search(r'POs: (.+)',b).group(1))]
    elif 'ROLLED' in s:
        r['kind']='rolled'
        r['so']=re.search(r'SO (\S+)',b).group(1)
        m=re.search(r'New ETD (\d+ \w+ \d+), ETA (\d+ \w+ \d+)',b); r['etd']=dmy(m.group(1)); r['eta']=dmy(m.group(2))
    elif s.startswith('Shipping Advice'):
        r['kind']='prealert'
        r['hbl']=re.search(r'HBL: (\S+)',b).group(1)
        m=re.search(r'Container/Seal: (\S+) / (\S+)',b); r['container']=m.group(1)
        r['vessel']=re.search(r'Vessel/Voyage: (.+)',b).group(1).strip()
        m=re.search(r'ATD (.+?): (\d+ \w+ \d+)',b); r['pol_name']=m.group(1); r['etd']=dmy(m.group(2))
        m=re.search(r'ETA (.+?): (\d+ \w+ \d+)',b); r['pod_name']=m.group(1); r['eta']=dmy(m.group(2))
        r['lines']=[(m.group(1),m.group(2),int(m.group(3)),int(m.group(4))) for m in re.finditer(r'(?m)^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs',b)]
    elif s.startswith('ETA update'):
        r['kind']='eta'
        r['hbl']=re.search(r'HBL (\S+)',s).group(1)
        r['eta']=dmy(re.search(r'revised ETA (\d+ \w+ \d+)',b).group(1))
    elif s.startswith('Arrival Notice'):
        r['kind']='arrival'
        r['hbl']=re.search(r'HBL (\S+)',s).group(1)
        m=re.search(r'arriving (.+?) on (\d+ \w+ \d+)',b); r['port']=m.group(1); r['date']=dmy(m.group(2))
    elif s.startswith('Receipt complete'):
        r['kind']='receipt'
        m=re.search(r'Receipt complete (\S+) - (\S+)',s); r['rcv'],r['ref']=m.groups()
    elif s.startswith('Entry Summary'):
        r['kind']='entry'
        r['entry']=re.search(r'Entry Summary (\S+) - (\S+)',s).group(1); r['ref']=re.search(r'Entry Summary (\S+) - (\S+)',s).group(2)
        g=lambda p: re.search(p+r': (\w+) ([\d,.]+)',b)
        r['cur']=g('Entered value').group(1); r['value']=num(g('Entered value').group(2))
        r['duty']=sum(float(num(g(k).group(2))) for k in ['Duty \(HTS\)','Section 301','Additional duties'])
        r['fees']=sum(float(num(g(k).group(2))) for k in ['MPF','HMF'])
        r['total']=float(num(g('Total duties and fees').group(2)))
    else: r['kind']='?'; print('UNKNOWN',s)
    ev.append(r)
if __name__=='__main__':
    from collections import Counter
    print(Counter(r['kind'] for r in ev))
    for r in ev:
        k=r['kind']
        if k=='booking': print(r['dt'].date(),'BOOK',r['so'],r['mode'],r['vessel'],r['pol'],r['pod'],r['etd'],r['eta'],r['pos'])
        if k=='rolled': print(r['dt'].date(),'ROLL',r['so'],r['etd'],r['eta'])
        if k=='prealert': print(r['dt'].date(),'PRE',r['hbl'],r['container'],r['vessel'],r['pol_name'],r['pod_name'],r['etd'],r['eta'],[(l[0],l[1],l[3]) for l in r['lines']])
        if k=='eta': print(r['dt'].date(),'ETA',r['hbl'],r['eta'])
        if k=='arrival': print(r['dt'].date(),'ARR',r['hbl'],r['port'],r['date'])
        if k=='entry': print(r['dt'].date(),'ENT',r['entry'],r['ref'],r['value'],r['duty'],r['fees'],r['total'])
        if k=='receipt': print(r['dt'].date(),'RCV',r['rcv'],r['ref'])
