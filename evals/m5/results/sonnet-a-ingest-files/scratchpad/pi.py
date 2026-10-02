import re,json,os
S='/private/tmp/claude-501/-private-var-folders-qj-j67my3-j6bzb4y5t82bvmkfh0000gn-T-m5-a-jtof532b/ingest/work/../d32f0a08-bc75-483b-9858-c586b6853c21/scratchpad'
D=os.path.dirname(os.path.abspath(__file__))+'/txt/'
pdfs={f:h for f,h,_ in json.load(open(os.path.dirname(os.path.abspath(__file__))+'/pdfs.json'))}
def num(s): return s.replace(',','')
def parse_pi(f):
    t=open(D+f+'.txt').read()
    d={'file':f,'hash':pdfs[f]}
    d['name_en']=t.split('\n')[1]; d['name_cn']=t.split('\n')[0]
    d['addr']=t.split('\n')[2]
    d['pi']=re.search(r'PI No\.: (\S+)',t).group(1)
    d['date']=re.search(r'Date: (\d{4}-\d\d-\d\d)',t).group(1)
    d['po']=re.search(r'Your PO: (PO-\d{4}-\d{4})',t).group(1)
    d['incoterm']=re.search(r'Price term: (.*)',t).group(1)
    d['pay']=re.search(r'Payment: (.*)',t).group(1)
    m=re.search(r'Delivery: about (\w+ \d+, \d{4}) \(ETD\)',t); d['etd']=m.group(1) if m else re.search(r'Delivery: (.*)',t).group(1)
    d['cur']=re.search(r'TOTAL (\w{3})',t).group(1)
    items=[]
    for m in re.finditer(r'(?m)^(\S+) (.+)\n.*\n([\d,]+) ([\d,]+) (\w{3}) ([\d,.]+) \w{3} ([\d,.]+)$',t):
        items.append(dict(item=m.group(1),qty=num(m.group(3)),ctns=num(m.group(4)),price=num(m.group(6)),amt=num(m.group(7))))
    d['items']=items
    return d
if __name__=='__main__':
    import sys
    for f in sorted(pdfs):
        if re.match(r'(HT-PI|LX|MJ|MT|QS|RF-PI|TY|YD)[^_]*\.pdf$',f):
            d=parse_pi(f); print(d['file'],d['pi'],d['date'],d['po'],d['cur'],d['etd'],'|',d['incoterm'],'|',d['pay'],len(d['items']),sum(float(i['qty'])*float(i['price']) for i in d['items'])) 
