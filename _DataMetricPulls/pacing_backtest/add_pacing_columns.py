# -*- coding: utf-8 -*-
"""SURGICAL: read the live 'New_Backtest_Clean_7.13.2026' tab column E (the pacing string that already
shows every strategy), split each pacing strategy into its OWN numeric column starting at AA, and add a
legend (AF-AG) explaining what each strategy is. Touches ONLY columns AA onward + their row-1/2 headers.
Does NOT read/clear/rewrite A:Z, so every hand edit in the existing trade grid is preserved."""
import os, re, sys
sys.stdout.reconfigure(encoding='utf-8')
from google.oauth2 import service_account
from googleapiclient.discovery import build
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),scopes=['https://www.googleapis.com/auth/spreadsheets'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds).spreadsheets(); SEE='1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg'; TAB='New_Backtest_Clean_7.13.2026'
E=sh.values().get(spreadsheetId=SEE,range=f"'{TAB}'!E3:E5000").execute().get('values',[])
def num(lab,s):
    m=re.search(re.escape(lab)+r'\s+(-?\d+)',s); return int(m.group(1)) if m else ''
grid=[]
for row in E:
    s=row[0] if row else ''
    grid.append(['','','',''] if not s else [num('Kalman',s),num('Accrual',s),num('Ensemble',s),num('Ens+Cap1.5',s)])
n=len(grid)
# ---- values (only AA onward) ----
sh.values().update(spreadsheetId=SEE,range=f"'{TAB}'!AA3",valueInputOption='RAW',body={'values':grid}).execute()
sh.values().update(spreadsheetId=SEE,range=f"'{TAB}'!AA1",valueInputOption='RAW',body={'values':[["PACING STRATEGIES  —  each model's projected final tweet count at this row's timestamp"]]}).execute()
sh.values().update(spreadsheetId=SEE,range=f"'{TAB}'!AA2",valueInputOption='RAW',body={'values':[['Kalman','AccrualCurve','Ensemble','Ens+Cap1.5 (LOCKED)']]}).execute()
legend=[['Pacing strategy','What it is'],
 ['Kalman','Filtered run-rate. Blends the prior-auction average tweets/hr with the rate observed so far this auction, extrapolated out to 48h. Reacts fast early, noisier early.'],
 ['AccrualCurve','Curve fit. Scales the current count up by the historical median share of a full auction\'s tweets that have already landed by this hour. Steadier, strongest late.'],
 ['Ensemble','Time-weighted blend of Kalman (weighted early) and AccrualCurve (weighted late). Blend weight cp = elapsed hours / 48.'],
 ['Ens+Cap1.5 (LOCKED)','The Ensemble, but the projected go-forward rate is capped at 1.5x the baseline rate (kills burst runaway). This is our LOCKED model and equals the "Our Pace" column (H).']]
sh.values().update(spreadsheetId=SEE,range=f"'{TAB}'!AF2",valueInputOption='RAW',body={'values':legend}).execute()
# ---- formatting (only AA onward) ----
def gid(t):
    for x in sh.get(spreadsheetId=SEE).execute()['sheets']:
        if x['properties']['title']==t: return x['properties']['sheetId']
g=gid(TAB)
LOW={'red':0.87,'green':0.93,'blue':0.99}; MID={'red':0.64,'green':0.80,'blue':0.93}; HIGH={'red':0.40,'green':0.61,'blue':0.84}
def rng(c): return [{'sheetId':g,'startRowIndex':2,'endRowIndex':2+n,'startColumnIndex':c,'endColumnIndex':c+1}]
reqs=[{'repeatCell':{'range':{'sheetId':g,'startRowIndex':2,'endRowIndex':2+n,'startColumnIndex':26,'endColumnIndex':30},'cell':{'userEnteredFormat':{'numberFormat':{'type':'NUMBER','pattern':'0'}}},'fields':'userEnteredFormat.numberFormat'}}]
for c in range(26,30):  # AA-AD get the same pace-band blue shading as H/I
    reqs.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':rng(c),'booleanRule':{'condition':{'type':'NUMBER_LESS','values':[{'userEnteredValue':'40'}]},'format':{'backgroundColor':LOW}}}}})
    reqs.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':rng(c),'booleanRule':{'condition':{'type':'NUMBER_BETWEEN','values':[{'userEnteredValue':'40'},{'userEnteredValue':'64'}]},'format':{'backgroundColor':MID}}}}})
    reqs.append({'addConditionalFormatRule':{'index':0,'rule':{'ranges':rng(c),'booleanRule':{'condition':{'type':'NUMBER_GREATER','values':[{'userEnteredValue':'64'}]},'format':{'backgroundColor':HIGH}}}}})
reqs+=[
 {'mergeCells':{'range':{'sheetId':g,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':26,'endColumnIndex':30},'mergeType':'MERGE_ALL'}},
 {'repeatCell':{'range':{'sheetId':g,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':26,'endColumnIndex':30},'cell':{'userEnteredFormat':{'horizontalAlignment':'CENTER','textFormat':{'bold':True}}},'fields':'userEnteredFormat(horizontalAlignment,textFormat)'}},
 {'repeatCell':{'range':{'sheetId':g,'startRowIndex':1,'endRowIndex':2,'startColumnIndex':26,'endColumnIndex':30},'cell':{'userEnteredFormat':{'horizontalAlignment':'CENTER','textFormat':{'bold':True}}},'fields':'userEnteredFormat(horizontalAlignment,textFormat)'}},
 {'repeatCell':{'range':{'sheetId':g,'startRowIndex':1,'endRowIndex':2,'startColumnIndex':31,'endColumnIndex':33},'cell':{'userEnteredFormat':{'textFormat':{'bold':True}}},'fields':'userEnteredFormat.textFormat'}},
 {'repeatCell':{'range':{'sheetId':g,'startRowIndex':1,'endRowIndex':7,'startColumnIndex':32,'endColumnIndex':33},'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(wrapStrategy,verticalAlignment)'}},
 {'updateDimensionProperties':{'range':{'sheetId':g,'dimension':'COLUMNS','startIndex':31,'endIndex':32},'properties':{'pixelSize':150},'fields':'pixelSize'}},
 {'updateDimensionProperties':{'range':{'sheetId':g,'dimension':'COLUMNS','startIndex':32,'endIndex':33},'properties':{'pixelSize':560},'fields':'pixelSize'}},
]
sh.batchUpdate(spreadsheetId=SEE,body={'requests':reqs}).execute()
nonblank=sum(1 for r in grid if r[0]!='')
print(f"DONE. wrote {n} rows to AA-AD ({nonblank} populated) = Kalman/Accrual/Ensemble/Ens+Cap1.5, plus legend AF2:AG6.")
print("sample row 3:",grid[0],"| row 4:",grid[1] if n>1 else '')
