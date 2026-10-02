import re,json,glob,os,hashlib
idx={os.path.basename(f):h for f,h,_ in json.load(open('idx.json'))}
sup={'NINGBO MINGTU':'NBBW','SHENZHEN HETAI':'SZHT','YIWU LANXIN':'YWLX','DONGGUAN RUIFENG':'DGRF','FOSHAN MINGJIA':'FSMJ','XIAMEN YUANDA':'XMYD','NINGBO QISHENG':'NBQS','HANGZHOU TIANYI':'HZTY'}
num=lambda s:s.replace(',','')
docs=[]
for f in sorted(idx):
    t=open(f'txt/{f}.txt').read(); name=f[:-4]
    d={'file':f,'hash':idx[f],'url':'supplier_docs/'+name+'.pdf'}
    if name.startswith('LCI'):
        d['kind']='qc'
        d['report']=re.search(r'Report No\.: (\S+)',t).group(1)
        d['date']=re.search(r'Inspection date: (\S+)',t).group(1)
        d['po']=re.search(r'PO No\.: (\S+)',t).group(1)
        d['result']=re.search(r'Overall result: (\S+)',t).group(1)
        d['n']=int(re.search(r'sample size (\d+)',t).group(1))
        d['agency']=t.split('\n')[0]
        d['supplier']=re.search(r'Supplier: (.*)',t).group(1)
    elif name.startswith('CI-PL'):
        d['kind']='cipl'
        d['date']=re.search(r'Date: (\S+)',t).group(1)
        d['po']=re.search(r'Order: (\S+)',t).group(1)
        m=re.search(r'From (\w+) to (\w+) by sea, (.*?)\s+Container: (\S+)\s+B/L: (\S+)',t)
        d['origin'],d['dest'],d['vessel'],d['container'],d['hbl']=m.groups()
        d['sup']=[v for k,v in sup.items() if k in t][0]
        ci=t.split('PACKING LIST')[0]; pl=t.split('PACKING LIST')[1]
        d['rows']=[(m.group(1),m.group(2),int(num(m.group(3)))) for m in re.finditer(r'^(\S+) .*\n.*\n(\d{4}\.\d\d\.\d{4}) ([\d,]+) \w{3} ',ci,re.M)]
        d['rows']=[]
        lines=ci.split('\n')
        for i,l in enumerate(lines):
            m=re.match(r'^(\S+) .*',l)
            mm=re.match(r'^(\d{4}\.\d\d\.\d{4}) ([\d,]+) [A-Z]{3} ([\d,.]+) [A-Z]{3} ([\d,.]+)$',l)
            if mm: d['rows'].append([lines[i-2].split()[0],mm.group(1),int(num(mm.group(2))),num(mm.group(3))])
        d['pl']={}
        for m in re.finditer(r'^[\d-]+ (\S+) (\d+) (\d+) ([\d,]+) ',pl,re.M): d['pl'][m.group(1)]=int(m.group(2))
    else:
        d['kind']='pi'
        d['date']=re.search(r'Date: (\S+)',t).group(1)
        d['pi']=re.search(r'PI No\.: (\S+)',t).group(1)
        d['po']=re.search(r'Your PO: (PO-\d+-\d+)',t).group(1)
        d['sup']=[v for k,v in sup.items() if k in t.upper()][0]
        d['etd']=re.search(r'about (\w+ \d+, \d+) \(ETD\)',t).group(1)
        d['cur']=re.search(r'(RMB|USD) [\d,.]+\n',t) and re.search(r'\b(RMB|USD) ',t).group(1)
        d['rows']=[]
        lines=t.split('\n')
        for i,l in enumerate(lines):
            mm=re.match(r'^([\d,]+) (\d+) (RMB|USD) ([\d,.]+) (RMB|USD) ([\d,.]+)$',l)
            if mm: d['rows'].append([lines[i-2].split()[0],int(num(mm.group(1))),mm.group(4),num(mm.group(6)),int(mm.group(2))])
        d['inco']=re.search(r'Price term: (.*)',t).group(1); d['pay']=re.search(r'Payment: (.*)',t).group(1)
    docs.append(d)
json.dump(docs,open('docs.json','w'),indent=0)
from collections import Counter
print(Counter(d['kind'] for d in docs))
for d in docs:
    if d['kind']!='qc' and not d['rows']: print('NOROWS',d['file'])
