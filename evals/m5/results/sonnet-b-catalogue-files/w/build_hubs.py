import json,re,csv,collections as C
T=json.load(open('../w/pdftext.json'))
pre={'MT':'NBBW','HT':'SZHT','LX':'YWLX','RF':'DGRF','MJ':'FSMJ','YD':'XMYD','QS':'NBQS','TY':'HZTY'}
fac={}
for f,t in T.items():
  if not f.startswith('CI-PL'): continue
  p=pre[re.match(r'CI-PL_([A-Z]+)',f).group(1)]; L=t.split('\n')
  for i,l in enumerate(L):
    m=re.match(r'^(\S+) (.+)$',l)
    if i+2<len(L) and re.match(r'^\d{4}\.\d{2}\.\d{4} ',L[i+2]) and m:
      fac[(p,m.group(1))]=(m.group(2),L[i+2].split()[0])
prods={};vs=[]
for l in open('shopify/products.jsonl'):
  d=json.loads(l)
  if 'sku' in d: d['ptitle']=prods[d['__parentId']]['title']; vs.append(d)
  else: prods[d['id']]=d
def canon(k):
  k=k.upper().replace('-FBA','')
  m=re.fullmatch(r'AH-?([A-Z]{3})-?0*(\d+)-?([A-Z]{3})',k)
  return f"AH-{m.group(1)}-{int(m.group(2)):04d}-{m.group(3)}"
SW={'BKL':'BLK','WTH':'WHT','SVL':'SLV','HFL':'HLF','BMA':'BAM'}
def canon2(k):
  c=canon(k); a,b,n,col=c.split('-'); return f"{a}-{b}-{n}-{SW.get(col,col)}"
hubs={}  # canonical -> dict
for v in vs: hubs[canon2(v['sku'])]=dict(shop=v)
fd={}
for h,d in hubs.items():
  s=d['shop']; fd[re.sub(r'[^a-z0-9]','',(s['ptitle']+s['title']).lower())]=h
fmap={}
for k,(desc,hs) in fac.items():
  key=re.sub(r'[^a-z0-9]','',desc.lower())
  fmap[k]=(fd.get(key),desc,hs)
if __name__=='__main__':
  print([ (k,v) for k,v in fmap.items() if not v[0]])
  print(len(set(v[0] for v in fmap.values())))
