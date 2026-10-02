import re,hashlib,email.utils,datetime as dt
RAW='/private/var/folders/qj/j67my3_j6bzb4y5t82bvmkfh0000gn/T/m5-b-sr5iskv6/ingest/work/exports/email/ops_inbox.mbox'
def emails():
    m=open(RAW,'rb').read()
    parts=[p for p in re.split(rb'(?m)^(?=From \S+@\S+ \w{3} \w{3} )',m) if p.strip()]
    out=[]
    for p in parts:
        t=p.decode('utf-8')
        hdr,_,body=t.partition('\n\n')
        h=dict(re.findall(r'(?m)^([A-Za-z-]+): (.*)$',hdr))
        date=email.utils.parsedate_to_datetime(h['Date'])
        out.append(dict(hash=hashlib.sha256(p.rstrip(b'\n')+b'\n').hexdigest(),url='mid:'+h['Message-ID'].strip('<>'),subject=h['Subject'],date=date,body=body,raw=t))
    return out
if __name__=='__main__':
    import collections
    es=emails();print(len(es))
    # check hash vs bytes: ensure each part starts with From and ends how?
    print(repr(es[0]['raw'][-80:]))
    for e in es:
        if e['subject'].startswith('Booking') and 'Xiamen' in e['subject']:
            print(e['body'][:700]);break
    for e in es:
        if e['subject'].startswith('Shipping') and 'LCL' not in e['subject']:
            print(e['body'][:900]);break
    for e in es:
        if e['subject'].startswith('Receipt') :
            pass
    for e in es:
        if e['subject'].startswith('Arrival') and 'LCL' in e['subject']: 
            pass
    c=collections.Counter()
    for e in es:
        for l in e['body'].split('\n'):
            k=re.sub(r'[0-9]','9',l)[:28]
            c[k]+=1
    for k,v in c.most_common(70): print(v,repr(k))
