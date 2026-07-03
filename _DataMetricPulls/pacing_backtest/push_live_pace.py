"""Reads live_pace.json + live market prices, maps each model to its bracket, and writes a
clean Google Sheet: per-model forecast + derivation, and the market's price ladder beside it."""
import json, math, os, urllib.request
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build

ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT = ROOT/'_DataMetricPulls'/'pacing_backtest'
P = json.loads((OUT/'live_pace.json').read_text())
SLUG = P['slug']

def gget(url):
    r=urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
    import json as j
    with urllib.request.urlopen(r,timeout=30) as resp: return j.loads(resp.read())

ev=gget(f"https://gamma-api.polymarket.com/events?slug={SLUG}")
mk=[]
if ev:
    for m in ev[0].get('markets',[]):
        lab=m.get('groupItemTitle','');
        try: op=json.loads(m.get('outcomePrices','[]')); mp=float(op[0]) if op else 0.0
        except Exception: mp=0.0
        mk.append(dict(lab=lab,mp=mp,ask=m.get('bestAsk'),bid=m.get('bestBid'),closed=bool(m.get('closed'))))

def rng(label):
    s=str(label).strip()
    try:
        if s.startswith('<'): return (0,int(s[1:])-1)
        if s.endswith('+'): return (int(s[:-1]),10**9)
        if '-' in s: a,b=s.split('-'); return (int(a),int(b))
        return (int(s),int(s))
    except Exception: return None
def bracket_for(f):
    for m in mk:
        r=rng(m['lab'])
        if r and r[0]<=f<=r[1]: return m['lab']
    return '?'

# market favorite + implied
openmk=[m for m in mk if not m['closed']]
fav=max(openmk,key=lambda m:m['mp']) if openmk else None
mforecasts=[r['forecast'] for r in P['models']]
med=sorted(mforecasts)[len(mforecasts)//2]

vals=[]
vals.append([f"ELON {SLUG.replace('elon-musk-of-tweets-','').upper()} (2-DAY) — LIVE PACING SNAPSHOT"])
vals.append([f"Snapshot: {P['now_utc'][:16]}Z   |   Window: {P['window_start_utc'][:16]}Z -> {P['window_end_utc'][:16]}Z"])
vals.append([f"Elapsed {P['elapsed_h']}h  |  Remaining {P['remaining_h']}h  |  Observed so far: {P['observed']} tweets  |  Current rate {P['current_rate_per_h']}/h  |  Usual rate {P['usual_rate_per_h']}/h  |  Priors used {P['n_priors']}"])
vals.append([f"Pulled type mix this window: {P['type_mix_pulled']}   (counted = originals+quotes+reposts+self-replies)"])
vals.append(["Counting rule (LOCKED): noon-ET window; originals+quotes+reposts+self-replies; off-feed replies & community reposts excluded. Verify live at xtracker.polymarket.com/user/elonmusk"])
vals.append([])
vals.append(["WHAT EACH PACER FORECASTS (final tweet count for this window)"])
vals.append(["Model","Category","Forecast","Implied bracket","How it arrives at that number"])
for r in sorted(P['models'],key=lambda x:x['forecast']):
    vals.append([r['model'],r['category'],r['forecast'],bracket_for(r['forecast']),r['how']])
vals.append([])
vals.append([f"Model spread: {min(mforecasts)} to {max(mforecasts)}   |   median {med}   |   best-ranked model = Kalman"])
vals.append([])
vals.append(["WHAT THE MARKET SAYS (live prices right now)"])
vals.append(["Bracket","Market prob (YES)","Ask","Bid"])
for m in sorted(openmk,key=lambda x:(rng(x['lab']) or (0,0))[0]):
    star=" <-- favorite" if fav and m['lab']==fav['lab'] else ""
    vals.append([m['lab']+star,round(m['mp'],3),m['ask'],m['bid']])
if fav:
    vals.append([])
    vals.append([f"Market favorite bracket: {fav['lab']} at {fav['mp']:.2f}.   Models cluster {min(mforecasts)}-{max(mforecasts)} (median {med})."])

creds=service_account.Credentials.from_service_account_file(
    os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'],
    subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds); dr=build('drive','v3',credentials=creds)
ss=sh.spreadsheets().create(body={'properties':{'title':f'Elon {SLUG.replace("elon-musk-of-tweets-","")} Live Pacing'},
    'sheets':[{'properties':{'title':'Live Pacing'}}]}).execute()
sid=ss['spreadsheetId']
sh.spreadsheets().values().update(spreadsheetId=sid,range='Live Pacing!A1',
    valueInputOption='RAW',body={'values':vals}).execute()
# light formatting: bold the title + section + header rows, freeze top, widen cols
def bold(r0,r1):
    return {'repeatCell':{'range':{'sheetId':0,'startRowIndex':r0,'endRowIndex':r1},
        'cell':{'userEnteredFormat':{'textFormat':{'bold':True}}},'fields':'userEnteredFormat.textFormat.bold'}}
reqs=[bold(0,1),bold(6,8),bold(12,14),
      {'updateDimensionProperties':{'range':{'sheetId':0,'dimension':'COLUMNS','startIndex':0,'endIndex':1},
        'properties':{'pixelSize':95},'fields':'pixelSize'}},
      {'updateDimensionProperties':{'range':{'sheetId':0,'dimension':'COLUMNS','startIndex':1,'endIndex':2},
        'properties':{'pixelSize':230},'fields':'pixelSize'}},
      {'updateDimensionProperties':{'range':{'sheetId':0,'dimension':'COLUMNS','startIndex':4,'endIndex':5},
        'properties':{'pixelSize':560},'fields':'pixelSize'}}]
sh.spreadsheets().batchUpdate(spreadsheetId=sid,body={'requests':reqs}).execute()
dr.permissions().create(fileId=sid,body={'role':'reader','type':'anyone'}).execute()
link=dr.files().get(fileId=sid,fields='webViewLink').execute()['webViewLink']
print("SHEET:",link)
print("market favorite:",fav['lab'] if fav else None, fav['mp'] if fav else None)
print("model implied brackets:",sorted(set(bracket_for(r['forecast']) for r in P['models'])))
