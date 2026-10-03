import re,hashlib,email,email.utils
from datetime import datetime,date
from zoneinfo import ZoneInfo
W='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-r-fnyh54rx/ingest/work/exports/'
def split_mbox(path):
    data=open(path,'rb').read()
    lines=data.split(b'\n')
    starts=[i for i,l in enumerate(lines) if l.startswith(b'From ') and (i==0 or lines[i-1]==b'')]
    msgs=[]
    for a,b in zip(starts,starts[1:]+[len(lines)]):
        chunk=lines[a:b]
        while chunk and chunk[-1]==b'': chunk.pop()
        msgs.append(b'\n'.join(chunk)+b'\n')
    return msgs
MON={m:i for i,m in enumerate('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec'.split(),1)}
def pdate(s):
    d,m,y=s.split(); return date(int(y),MON[m],int(d))
def mail_docs():
    out=[]
    for raw in split_mbox(W+'email/ops_inbox.mbox'):
        first,rest=raw.split(b'\n',1)
        msg=email.message_from_bytes(rest)
        body=msg.get_payload(decode=True).decode('utf-8')
        subj=msg['Subject']
        d=dict(hash=hashlib.sha256(raw).hexdigest(),url='mid:'+msg['Message-ID'].strip('<>'),issued=email.utils.parsedate_to_datetime(msg['Date']),subj=subj,body=body)
        if subj.startswith('Booking Confirmation'):
            d['kind']='booking'
            g=lambda p:re.search(p,body).group(1)
            d['so']=g(r'SO: (\S+)'); d['equip']=g(r'Equipment: (.+)'); d['vessel']=g(r'Vessel/Voyage: (.+)')
            m=re.search(r'POL: .*\((\w+)\)\s+POD: .*\((\w+)\)',body); d['pol'],d['pod']=m.groups()
            d['etd']=pdate(g(r'ETD: (.+)')); d['eta']=pdate(g(r'ETA: (.+)')); d['pos_raw']=g(r'POs: (.+)')
        elif subj.startswith('RE: Booking Confirmation'):
            d['kind']='rolled'
            m=re.search(r'rolled SO (\S+) .* New ETD (\d+ \w+ \d+), ETA (\d+ \w+ \d+)',body)
            d['so']=m.group(1); d['etd']=pdate(m.group(2)); d['eta']=pdate(m.group(3))
        elif subj.startswith('Shipping Advice'):
            d['kind']='prealert'
            g=lambda p:re.search(p,body).group(1)
            d['hbl']=g(r'HBL: (\S+)'); cs=g(r'Container/Seal: (\S+) /'); d['container']=None if cs=='LCL' else cs
            d['vessel']=g(r'Vessel/Voyage: (.+)'); d['atd']=pdate(g(r'ATD [\w ]+: (.+)')); d['eta']=pdate(g(r'ETA [\w /]+: (.+)'))
            d['lines']=[dict(po=m.group(1),item=m.group(2),ctns=m.group(3),qty=m.group(4)) for m in re.finditer(r'^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs',body,re.M)]
            d['origin_name']=re.search(r'ATD ([\w ]+):',body).group(1)
        elif subj.startswith('ETA update'):
            d['kind']='eta'
            d['hbl']=re.search(r'HBL (\S+)',subj).group(1)
            d['eta']=pdate(re.search(r'revised ETA (\d+ \w+ \d+)',body).group(1))
        elif subj.startswith('Arrival Notice'):
            d['kind']='arrival'
            m=re.search(r'Shipment HBL (\S+) \((\S+)\) on (.+?) is arriving (.+?) on (\d+ \w+ \d+)',body)
            d['hbl'],d['cont'],d['vessel'],d['port'],d['date']=m.group(1),m.group(2),m.group(3),m.group(4),pdate(m.group(5))
        elif subj.startswith('Entry Summary'):
            d['kind']='entry'
            g=lambda p:re.search(p,body).group(1).replace(',','')
            d['entry']=g(r'Entry (\S+) filed for'); d['ref']=g(r'filed for (\S+)\.')
            d['value']=g(r'Entered value: USD ([\d,.]+)'); d['hts']=g(r'Duty \(HTS\): USD ([\d,.]+)'); d['s301']=g(r'Section 301: USD ([\d,.]+)')
            d['add']=g(r'Additional duties: USD ([\d,.]+)'); d['mpf']=g(r'MPF: USD ([\d,.]+)'); d['hmf']=g(r'HMF: USD ([\d,.]+)'); d['total']=g(r'Total duties and fees: USD ([\d,.]+)')
        elif subj.startswith('Receipt complete'):
            d['kind']='receipt'
            m=re.search(r'Receiving complete for (\S+) under (\S+)',body); d['ref'],d['rcv']=m.groups()
            d['disc']=re.findall(r'^\s+(\S+) \((\S+)\): expected (\d+), received (\d+), damaged (\d+)',body,re.M)
        else: raise Exception(subj)
        out.append(d)
    return out
if __name__=='__main__':
    from collections import Counter
    ds=mail_docs(); print(Counter(d['kind'] for d in ds))
    from decimal import Decimal as D
    for d in ds:
        if d['kind']=='entry': assert D(d['hts'])+D(d['s301'])+D(d['add'])+D(d['mpf'])+D(d['hmf'])==D(d['total']),d['entry']
    print(len({d['hash'] for d in ds}))
    for d in ds:
        if d['kind']=='receipt' and d['disc']: print(d['ref'],d['disc'])
