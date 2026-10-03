from common import *
import pickle,time
name,rel=sys.argv[1],sys.argv[2]; lo=int(sys.argv[3]); hi=int(sys.argv[4])
f=pickle.load(open(name,'rb'))[lo:hi]
t=time.time(); write(f,[rel],None,chunk=4000,label=f'{name}[{lo}:{hi}]'); print(round(time.time()-t,1),'s')
