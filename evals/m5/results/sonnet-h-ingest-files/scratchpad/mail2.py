import re,pickle
import parse_mail as pm
def build():
    E=pm.parse_all()
    for e in E:
        s=e['subject']; b=e['body']
        if s.startswith('Booking Confirmation'):
            e.update(kind='booking',so=re.search(r'SO: (\S+)',b).group(1),equip=re.search(r'Equipment: (.*)',b).group(1),vessel=re.search(r'Vessel/Voyage: (.*)',b).group(1),
              pol=re.search(r'POL: .*\((\w+)\)  POD: .*\((\w+)\)',b).groups(),etd=pm.dt(re.search(r'ETD: (.*)',b).group(1)),eta=pm.dt(re.search(r'ETA: (.*)',b).group(1)),
              pos=re.search(r'POs: (.*)',b).group(1),shipper=re.search(r'Shipper\(s\): (.*)',b).group(1))
        elif s.startswith('RE: Booking'):
            m=re.search(r'rolled SO (\S+) .*New ETD (.*?), ETA (.*?)\. ',b)
            e.update(kind='roll',so=m.group(1),etd=pm.dt(m.group(2)),eta=pm.dt(m.group(3)))
        elif s.startswith('Shipping Advice'):
            c=re.search(r'Container/Seal: (\S+) / (\S+)',b)
            m=re.search(r'ATD (\w+): (.*)\nETA (.*?): (.*)\n',b)
            e.update(kind='prealert',hbl=re.search(r'HBL: (\S+)',b).group(1),container=c.group(1),vessel=re.search(r'Vessel/Voyage: (.*)',b).group(1),
              atd_port=m.group(1),atd=pm.dt(m.group(2)),eta_port=m.group(3),eta=pm.dt(m.group(4)),
              lines=[(a,b_,int(c_),int(d_)) for a,b_,c_,d_ in re.findall(r'^\s+(PO-\d{4}-\d{4})\s+(\S+)\s+(\d+) ctns\s+(\d+) pcs',b,re.M)])
        elif s.startswith('ETA update'):
            m=re.search(r'revised ETA (.*?) for HBL (\S+)',b); e.update(kind='eta',hbl=m.group(2),eta=pm.dt(m.group(1)))
        elif s.startswith('Arrival'):
            m=re.search(r'Shipment HBL (\S+) \((\S+)\) on (.*?) is arriving (.*?) on (.*?)\.\n',b)
            e.update(kind='arrival',hbl=m.group(1),container=m.group(2),vessel=m.group(3),port=m.group(4),day=pm.dt(m.group(5)))
        elif s.startswith('Receipt'):
            m=re.search(r'Receipt complete (\S+) - (\S+)',s)
            e.update(kind='receipt',rcv=m.group(1),ref=m.group(2),disc=b.split('Discrepancies:')[1].split('Thanks')[0].strip() if 'Discrepancies' in b else '')
        elif s.startswith('Entry Summary'):
            f=lambda p: re.search(p,b).group(1).replace(',','')
            e.update(kind='entry',entry=re.search(r'Entry (\S+) filed for',b).group(1),ref=re.search(r'filed for (\S+)\.',b).group(1),
              value=f(r'Entered value: USD ([\d,.]+)'),hts=f(r'Duty \(HTS\): USD ([\d,.]+)'),s301=f(r'Section 301: USD ([\d,.]+)'),
              add=f(r'Additional duties: USD ([\d,.]+)'),mpf=f(r'MPF: USD ([\d,.]+)'),hmf=f(r'HMF: USD ([\d,.]+)'),total=f(r'Total duties and fees: USD ([\d,.]+)'))
        else: raise Exception(s)
    return E
