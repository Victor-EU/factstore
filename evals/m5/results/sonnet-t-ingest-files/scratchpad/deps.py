from load import *
from decimal import Decimal as D, ROUND_HALF_UP
import collections,re
ACK=re.compile(r'^(定金收到了，马上安排生产|收到，谢谢|Received, thank you|大货生产中|OK)$')
def q2(x): return x.quantize(D('0.01'),ROUND_HALF_UP)
def deposits_and_acks(pis, ch):
    by=collections.defaultdict(list)
    for d in ch: by[d['sup']].append(d)
    res_dep=[]; res_ack=[]; issues=[]
    for sup,ms in by.items():
        sp=[p for p in pis if p['sup_code']==sup]
        deps=[]
        for m in ms:
            if not m['ours']: continue
            t=m['text']
            x=re.search(r'deposit for (PO-\d+-\d+) \((?:USD|CNY) ([\d,]+\.\d\d)\)',t)
            y=re.search(r'Deposit paid today, (?:USD|CNY) ([\d,]+\.\d\d)',t)
            if x:
                p=[p for p in sp if p['po']==x.group(1)]
                amt=D(num(x.group(2)))
                if not p or q2(D(p[0]['total'])*p[0]['deposit_pct']/100)!=amt: issues.append(('named mismatch',m['url'],x.group(1)))
                deps.append(dict(m=m,po=x.group(1),amt=amt,named=True))
            elif y:
                amt=D(num(y.group(1)))
                c=[p['po'] for p in sp if q2(D(p['total'])*p['deposit_pct']/100)==amt]
                if len(c)!=1: issues.append(('unnamed unresolved',m['url'],c)); continue
                deps.append(dict(m=m,po=c[0],amt=amt,named=False))
        res_dep+=deps
        pend=list(deps)
        for m in ms:
            if m['ours'] or not ACK.match(m['text']): continue
            cand=[d for d in pend if d['m']['issued']<m['issued']]
            if not cand: issues.append(('ack without deposit',m['url'],m['text'])); continue
            d=cand[0]; pend.remove(d)
            res_ack.append(dict(m=m,dep=d))
        for d in pend: issues.append(('unacked deposit',d['m']['url'],d['po']))
    return res_dep,res_ack,issues
if __name__=='__main__':
    pis=[d for d in pdf_docs() if d['kind']=='pi']
    dep,ack,iss=deposits_and_acks(pis,chat_docs())
    for a in sorted(ack,key=lambda a:(a['m']['sup'],a['m']['issued'])):
        print(a['m']['sup'],a['m']['issued'].strftime('%Y-%m-%d %H:%M'),a['m']['text'][:6],'=> dep',a['dep']['m']['issued'].strftime('%m-%d %H:%M'),a['dep']['po'],'named' if a['dep']['named'] else 'AMT')
    print(len(dep),len(ack)); 
    for i in iss: print(i)
