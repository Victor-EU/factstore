import pickle,os,random
S=os.environ['S'];cust=pickle.load(open(S+'/cust.pkl','rb'));ed=pickle.load(open(S+'/edges.pkl','rb'))
for rule in ('mailbox','name+address'):
    L=[(n,o) for n,(o,r,c) in ed.items() if r==rule]
    print(rule,'name differs:',sum(1 for n,o in L if cust[n]['name']!=cust[o]['name']),'zip differs',sum(1 for n,o in L if cust[n]['addr'][0][1]!=cust[o]['addr'][0][1]))
    random.seed(1)
    for n,o in random.sample(L,10): print('  ',cust[n]['email'],cust[n]['name'],cust[n]['addr'],'|',cust[o]['email'],cust[o]['name'],cust[o]['addr'])
