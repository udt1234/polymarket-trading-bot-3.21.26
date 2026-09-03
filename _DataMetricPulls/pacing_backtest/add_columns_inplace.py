# -*- coding: utf-8 -*-
"""SURGICAL, IN PLACE: add the decision columns + row-2 header descriptions to the two EXISTING sheets
Sir pointed at (same URLs, preserves each doc's trade set). Seesaw = full fair-value set with live
Kelly/EV/shares/value formulas + a Config tab. Speed = same header set, with pace/fair/Kelly/EV marked
n/a (it's a reactive taker scalp, no fair-value model) + a live Move formula."""
import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds)
SEE='1aApOzCaK7nbg2PRrNW_N1apVv1GWxjd6BHJZD9L7Feg'; SPD='1B7dBGHy6ozJAs11yIDk5yMZKDljKeWhrwDqUtp2Nn2k'
DARK={'red':0.13,'green':0.18,'blue':0.22}; GRAY={'red':0.92,'green':0.92,'blue':0.92}
def rd(SID,tab,rng): return sh.spreadsheets().values().get(spreadsheetId=SID,range=f"'{tab}'!{rng}",valueRenderOption='UNFORMATTED_VALUE').execute().get('values',[])
def gid(SID,title):
    for s in sh.spreadsheets().get(spreadsheetId=SID).execute()['sheets']:
        if s['properties']['title']==title: return s['properties']['sheetId']
    return None
def write(SID,tab,grid): sh.spreadsheets().values().update(spreadsheetId=SID,range=f"'{tab}'!A1",valueInputOption='USER_ENTERED',body={'values':grid}).execute()
def fmt(SID,tab,ncol,ndesc_wrap=True,buysell_col=None,nrows=0,widths=None):
    sid=gid(SID,tab); reqs=[]
    reqs.append({'updateSheetProperties':{'properties':{'sheetId':sid,'gridProperties':{'frozenRowCount':2}},'fields':'gridProperties.frozenRowCount'}})
    reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':0,'endRowIndex':1,'startColumnIndex':0,'endColumnIndex':ncol},'cell':{'userEnteredFormat':{'backgroundColor':DARK,'textFormat':{'bold':True,'foregroundColor':{'red':1,'green':1,'blue':1}}}},'fields':'userEnteredFormat(backgroundColor,textFormat)'}})
    reqs.append({'repeatCell':{'range':{'sheetId':sid,'startRowIndex':1,'endRowIndex':2,'startColumnIndex':0,'endColumnIndex':ncol},'cell':{'userEnteredFormat':{'backgroundColor':GRAY,'textFormat':{'italic':True,'fontSize':9},'wrapStrategy':'WRAP','verticalAlignment':'TOP'}},'fields':'userEnteredFormat(backgroundColor,textFormat,wrapStrategy,verticalAlignment)'}})
    if buysell_col is not None:
        for val,color in [("BUY",{'red':0.83,'green':0.94,'blue':0.83}),("SELL",{'red':0.99,'green':0.90,'blue':0.80})]:
            reqs.append({'addConditionalFormatRule':{'rule':{'ranges':[{'sheetId':sid,'startRowIndex':2,'endRowIndex':nrows+2,'startColumnIndex':buysell_col,'endColumnIndex':buysell_col+1}],'booleanRule':{'condition':{'type':'TEXT_EQ','values':[{'userEnteredValue':val}]},'format':{'backgroundColor':color}}},'index':0}})
    if widths:
        for ci,w in widths: reqs.append({'updateDimensionProperties':{'range':{'sheetId':sid,'dimension':'COLUMNS','startIndex':ci,'endIndex':ci+1},'properties':{'pixelSize':w},'fields':'pixelSize'}})
    sh.spreadsheets().batchUpdate(spreadsheetId=SID,body={'requests':reqs}).execute()

# ---------- SEESAW ----------
# Config tab
try: sh.spreadsheets().batchUpdate(spreadsheetId=SEE,body={'requests':[{'addSheet':{'properties':{'title':'Config'}}}]}).execute()
except Exception: pass
write(SEE,'Config',[["SEESAW CONFIG (edit B2:B4 - Every Trade shares/value/EV recompute)"],["Bankroll ($)",5000],["Kelly fraction",0.25],["Clip cap ($ per buy)",40]])
# Every Trade rebuild (preserve the 236 rows already in the doc)
et=rd(SEE,'Every Trade','A2:J')
ehdr=['Time (ET)','Hrs to close','Action','Bracket','What we are pacing (count)','PM odds','Our fair','Edge','Kelly fraction','Expected value ($)','Shares','Total value ($)']
edesc=['When the trade fired (Eastern)','Hours left until the auction resolves','BUY = market below our fair; SELL = market above our fair','The tweet-count bracket traded',
 'Our projected final tweet count driving this trade (our center)',"Polymarket's price for this bracket = the market's implied probability",'Our fair probability this bracket wins (pace + shrinking uncertainty)',
 'Our fair minus the market price. + = underpriced (buy), - = overpriced (sell)','Kelly bet fraction = edge / (1 - price)','Shares x edge = expected profit of this clip [formula]',
 'Kelly-sized: MIN(bankroll x fraction x Kelly, clip cap) / price [formula]','Shares x price = dollars deployed [formula]']
grid=[ehdr,edesc]
for i,e in enumerate(et):
    R=i+3
    grid.append([e[0],e[1],e[2],e[3],e[7],e[4],e[5], f"=G{R}-F{R}", f"=(G{R}-F{R})/(1-F{R})", f"=K{R}*(G{R}-F{R})", f"=MIN(Config!$B$2*Config!$B$3*I{R},Config!$B$4)/F{R}", f"=K{R}*F{R}"])
write(SEE,'Every Trade',grid); fmt(SEE,'Every Trade',12,buysell_col=2,nrows=len(et),widths=[(0,120),(4,150),(9,130),(10,100),(11,110)])
# Per-Post Pace: add row-2 descriptions, keep 77 rows
pp=rd(SEE,'Per-Post Pace','A2:H')
phdr=['tweet_no','et','hrs_to_close','count_so_far','center_before','center_after','per_post_move','sigma']
pdesc=['Nth counted tweet in the auction','When the tweet posted (Eastern)','Hours left until resolution','Tweets counted so far',
 'Our projected final count just BEFORE this tweet','Our projected final count just AFTER this tweet','How much this ONE tweet moved our projection (accurate late, wild early)','Our uncertainty band in tweets; shrinks as time runs out']
write(SEE,'Per-Post Pace',[phdr,pdesc]+pp); fmt(SEE,'Per-Post Pace',8,widths=[(1,130)])

# ---------- SPEED (same header set; pace/fair/Kelly/EV = n/a for a taker scalp) ----------
shdr=['Auction','Time (ET)','Bracket (+1 target)','What we are pacing','PM odds (buy)','PM odds (sell)','Our fair','Move (cents/share)','Kelly fraction','Expected value ($)','Shares','Total value ($)','P&L ($)']
sdesc=['Which auction','When the tweet fired our buy (Eastern)','The next-higher bracket we bought to catch the jump','n/a - reactive taker scalp, no pace/fair model',
 'Price we paid walking UP the ask ladder (VWAP)','Price we sold at walking DOWN the bid ladder (VWAP)','n/a - no fair-value model for the speed scalp',
 'Sell minus buy in cents = the round-trip move captured [formula]','n/a - no edge/fair to size against','n/a - the outcome is the realized P&L at right',
 'Shares filled walking the real ask ladder','Dollars deployed on the clip (spent)','Realized profit/loss on the round trip']
for tab in ['Trades 27-29','Trades 25-27']:
    d=rd(SPD,tab,'A2:H'); grid=[shdr,sdesc]
    for i,e in enumerate(d):
        R=i+3
        grid.append([e[0],e[1],e[2],'n/a',e[3],e[4],'n/a', f"=(F{R}-E{R})*100", 'n/a','n/a', e[5],e[6],e[7]])
    write(SPD,tab,grid); fmt(SPD,tab,13,widths=[(0,150),(1,140),(2,130),(3,120),(6,90),(7,120),(9,120)])
print("DONE. Seesaw:",f"https://docs.google.com/spreadsheets/d/{SEE}/edit","| Speed:",f"https://docs.google.com/spreadsheets/d/{SPD}/edit")
