import json,re
docs=json.load(open('docs.json'))
sup={'NINGBO MINGTU HOUSEWARES CO., LTD.':'NBBW','SHENZHEN HETAI ELECTRIC APPLIANCE CO., LTD.':'SZHT','YIWU LANXIN TEXTILE CO., LTD.':'YWLX','DONGGUAN RUIFENG SILICONE PRODUCTS CO., LTD.':'DGRF','FOSHAN MINGJIA CERAMICS CO., LTD.':'FSMJ','XIAMEN YUANDA BAMBOO PRODUCTS CO., LTD.':'XMYD','NINGBO QISHENG STAINLESS STEEL CO., LTD.':'NBQS','HANGZHOU TIANYI GLASSWARE CO., LTD.':'HZTY'}
store=set(l.strip() for l in open('codes.txt'))
hs={}
for l in open('hs.txt'):
    c,h=l.split();hs[c]=h
pos={}
for d in docs:
    if d['kind']=='PI':
        s=sup.get(d['supplier_en']) ; d['sup']=s
        if not s: print('nosup',d['file'],d['supplier_en'])
        if d['po'] in pos: print('dup PO',d['po'])
        pos[d['po']]={'sup':s,'items':{i['code']:i for i in d['items']},'pi':d}
        for i in d['items']:
            if f"{s}:{i['code']}" not in store: print('PI no sku',d['file'],s,i['code'])
        if len(set(i['cur'] for i in d['items']))>1: print('mixed cur',d['file'])
for d in docs:
    if d['kind']=='CI':
        p=pos.get(d['po'])
        if not p: print('CI no PO',d['file']);continue
        s=p['sup']
        if d['supplier_en'] not in sup or sup[d['supplier_en']]!=s: print('CI supplier mismatch',d['file'])
        for r in d['rows']:
            k=f"{s}:{r['code']}"
            if k not in store: print('CI no sku',d['file'],k)
            if r['code'] not in p['items']: print('CI item not in PO',d['file'],k)
            elif r['qty']!=p['items'][r['code']]['qty']: print('CI qty differs from PI',d['file'],k,r['qty'],p['items'][r['code']]['qty'])
            if hs.get(k)!=r['hs']: print('HS differs',d['file'],k,hs.get(k),r['hs'])
        if set(r['code'] for r in d['rows'])!=set(p['items']): print('CI covers subset',d['file'],len(d['rows']),len(p['items']))
    if d['kind']=='QC':
        if d['po'] not in pos: print('QC no PO',d['file'])
        elif sup.get(d['supplier_en'],None) is None and d['supplier_en'].upper() not in sup: print('QC sup?',d['supplier_en'])
        elif sup.get(d['supplier_en'].upper())!=pos[d['po']]['sup']: print('QC sup mismatch',d['file'])
from collections import defaultdict
h=defaultdict(list)
for d in docs:
    if d['kind']=='CI': h[d['hbl']].append(d)
for k,v in h.items():
    if len(v)>1:
        print(k,[(x['po'],x['container'],x['vessel'],x['origin'],x['dest'],x['date']) for x in v])
cpo=defaultdict(list)
for d in docs:
    if d['kind']=='CI': cpo[d['po']].append(d['hbl'])
print({k:v for k,v in cpo.items() if len(v)>1})
print([p for p in pos if p not in cpo])
qc=defaultdict(list)
for d in docs:
    if d['kind']=='QC': qc[d['po']].append((d['date'],d['result']))
print({k:v for k,v in qc.items() if len(v)>1}); print([p for p in pos if p not in qc])
