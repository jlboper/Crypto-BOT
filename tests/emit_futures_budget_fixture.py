"""Synthetic Python-to-Worker size contract; no database or exchange access."""
import json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.export_paper_snapshot import compatible_remote_projection
f={'enabled':True,'killed':True,'symbols':[f'COIN{i}USDT' for i in range(15)],
   'positions':[{'symbol':f'COIN{i}USDT','quantity':1} for i in range(10)],
   'position':None,'automatic_leverage':1,'closed_trades':500,'gross_pnl':-31.25,
   'native_protection':{'supported':True,'positions':{'GNSUSDT':{'status':'BLOCKED','unprotected_quantity':24.86}}},
   'signals':[{'i':i,'text':'x'*1000} for i in range(50)],
   'trades':[{'i':i,'text':'x'*1000} for i in range(50)],
   'equity':[{'i':i,'text':'x'*1000} for i in range(120)],
   'shadow_scorecard':[{'i':i,'text':'x'*1000} for i in range(27)]}
d={'status':{'mode':'TESTNET'},'positions':[],'equity':[],'trades':[],'reviews':[],'events':[],
   'research':{'assets':[]},'futures_forward':f}
print(json.dumps(compatible_remote_projection(d),separators=(',',':')))
