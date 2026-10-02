import re,hashlib,email,email.utils,json
from datetime import datetime
ROOT='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-f-pyk9rvda/ingest/work/exports'
def load():
    raw=open(ROOT+'/email/ops_inbox.mbox','rb').read()
    parts=[p for p in re.split(rb'(?m)^(?=From \S+@\S+ )',raw) if p.strip()]
    out=[]
    for p in parts:
        p=p.rstrip(b'\n')+b'\n'
        t=p.decode()
        hdr,body=t.split('\n\n',1)
        g=lambda k:re.search(r'(?m)^%s: (.*)$'%k,hdr).group(1)
        r=dict(hash=hashlib.sha256(p).hexdigest(),mid=g('Message-ID').strip('<>'),subject=g('Subject'),date=g('Date'),frm=g('From'))
        r['url']='mid:'+r['mid']
        r['issued']=email.utils.parsedate_to_datetime(r['date']).isoformat()
        r['body']=body
        s=r['subject']
        if s.startswith('RE: Booking'): r['kind']='roll'
        elif s.startswith('Booking Conf'): r['kind']='booking'
        elif s.startswith('Shipping Advice'): r['kind']='prealert'
        elif s.startswith('ETA update'): r['kind']='eta'
        elif s.startswith('Arrival'): r['kind']='arrival'
        elif s.startswith('Receipt'): r['kind']='receipt'
        elif s.startswith('Entry'): r['kind']='entry'
        else: r['kind']='?'
        out.append(r)
    return out
if __name__=='__main__':
    L=load()
    for r in L:
        b=' | '.join(l.strip() for l in r['body'].split('\n')[2:] if l.strip() and not l.startswith(('Best','Jenny','Ocean','Pacific','T +','This email','Regards','Tom','Licensed','Harborline','Thanks','Receiving','Garden','Dear','Hi ')))
        print(r['kind'],r['issued'][:16],b[:420])
