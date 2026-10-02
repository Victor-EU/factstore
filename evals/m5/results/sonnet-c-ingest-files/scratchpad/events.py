from parse import *
import collections
def dmy(s):
    m=re.match(r'(\d+) (\w{3}) (\d{4})',s); return dt.date(int(m.group(3)),MON[m.group(2)],int(m.group(1)))
def parse_mail_events(mails,po_universe):
    ev=[]
    def fullpo(tok):
        tok=tok.strip()
        m=re.match(r'(?i)PO[-# ]*(\d{4})-(\d{4})$',tok)
        if m: return f'PO-{m.group(1)}-{m.group(2)}'
        m=re.match(r'(?i)PO[ #]*0*(\d+)$',tok); n=int(m.group(1))
        c=[p for p in po_universe if int(p[-4:])==n]
        assert len(c)==1,(tok,c)
        return c[0]
    for m in mails:
        s=m['subject']; b=m['body']; e=dict(m); 
        if s.startswith('Booking Confirmation'):
            e['type']='booking'
            e['so']=re.search(r'^SO: (\S+)',b,re.M).group(1)
            e['mode']=re.search(r'^Equipment: (\S+)',b,re.M).group(1)
            e['mode']={'LCL':'LCL'}.get(e['mode']) or re.sub(r'^\d+x','',e['mode'])
            e['vessel']=re.search(r'^Vessel/Voyage: (.*)',b,re.M).group(1)
            pol,pod=re.search(r'POL: .*\((\w+)\)\s+POD: .*\((\w+)\)',b).groups()
            e['origin'],e['dest']=pol,pod
            e['etd']=dmy(re.search(r'^ETD: (.*)',b,re.M).group(1)); e['eta']=dmy(re.search(r'^ETA: (.*)',b,re.M).group(1))
            e['pos']=[fullpo(x) for x in re.search(r'^POs: (.*)',b,re.M).group(1).split(',')]
            e['shippers']=re.search(r'^Shipper\(s\): (.*)',b,re.M).group(1)
        elif s.startswith('RE: Booking'):
            e['type']='rolled'
            e['so']=re.search(r'SO (\S+) - ROLLED',s).group(1)
            m2=re.search(r'New ETD (\d+ \w+ \d+), ETA (\d+ \w+ \d+)',b)
            e['etd']=dmy(m2.group(1)); e['eta']=dmy(m2.group(2))
        elif s.startswith('Shipping Advice'):
            e['type']='prealert'
            e['hbl']=re.search(r'^HBL: (\S+)',b,re.M).group(1)
            cont,seal=re.search(r'^Container/Seal: (\S+) / (\S+)',b,re.M).groups()
            e['container']=None if cont=='LCL' else cont
            e['vessel']=re.search(r'^Vessel/Voyage: (.*)',b,re.M).group(1)
            m2=re.search(r'^ATD (.*?): (.*)',b,re.M); e['origin']=PORTS[m2.group(1)]; e['atd']=dmy(m2.group(2))
            m2=re.search(r'^ETA (.*?): (.*)',b,re.M); e['dest']=PORTS[m2.group(1)]; e['eta']=dmy(m2.group(2))
            e['lines']=[(a,c,int(d),int(f)) for a,c,d,f in re.findall(r'^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs',b,re.M)]
            e['pk']=re.search(r'^Packages: (\d+) CTNS',b,re.M).group(1)
        elif s.startswith('ETA update'):
            e['type']='eta'
            e['hbl']=re.search(r'HBL (\S+)',s).group(1)
            e['eta']=dmy(re.search(r'revised ETA (\d+ \w+ \d{4})',b).group(1))
        elif s.startswith('Arrival Notice'):
            e['type']='arrival'
            m2=re.search(r'Shipment HBL (\S+) \((\S+)\) on (MV .*?) is arriving (.*?) on (\d+ \w+ \d{4})',b)
            e['hbl'],e['container']=m2.group(1),m2.group(2); e['vessel']=m2.group(3); e['dest']=PORTS[m2.group(4)]; e['eta']=dmy(m2.group(5))
        elif s.startswith('Entry Summary'):
            e['type']='entry'
            m2=re.search(r'Entry (\S+) filed for (\S+)\.',b); e['entry']=m2.group(1); e['ref']=m2.group(2)
            g=lambda k: num(re.search(k+r': USD ([\d,.]+)',b).group(1))
            e['value']=g('Entered value'); e['hts']=g(r'Duty \(HTS\)')
            e['s301']=g('Section 301') if 'Section 301' in b else '0'
            e['add']=g('Additional duties'); e['mpf']=g('MPF'); e['hmf']=g('HMF'); e['total']=g('Total duties and fees')
            e['other']=re.findall(r'^(.*): USD',b,re.M)
        elif s.startswith('Receipt complete'):
            e['type']='receipt'
            m2=re.search(r'Receiving complete for (\S+) under (\S+) \(ASN (\S+)\)',b)
            e['ref'],e['rcv'],e['asn']=m2.groups()
            e['disc']=re.findall(r'^\s+(ACMH-\d+) \((.*?)\): expected (\d+), received (\d+), damaged (\d+)',b,re.M)
        else: raise Exception(s)
        ev.append(e)
    return ev
if __name__=='__main__':
    mails=parse_mail()
    pos=set()
    for c in parse_chats():
        pos|=set(re.findall(r'PO-\d{4}-\d{4}',c['text']))
    ev=parse_mail_events(mails,pos)
    print(collections.Counter(e['type'] for e in ev))
    for e in ev:
        if e['type']=='entry':
            tot=float(e['hts'])+float(e['s301'])+float(e['add'])+float(e['mpf'])+float(e['hmf'])
            if abs(tot-float(e['total']))>0.02 or len(e['other'])!=7 and 0: print('entry mismatch',e['entry'],tot,e['total'],e['other'])
    import pickle; pickle.dump(ev,open('mailev.pkl','wb'))
