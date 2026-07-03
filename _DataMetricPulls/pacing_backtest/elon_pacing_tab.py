"""Rebuild the 'Elon Pacing' tab: live formula-driven, 2-day + 7-day, all models off your tabs,
plus 3 sleep-aware models (Linear_S/Kalman_S/M4MMPP_S = rate x effective-hours, where effective
hours weight the remaining clock-hours by Elon's hour-of-day profile so 3-9am ET adds ~0).
Includes plain-English definitions row, live balance + fractional-Kelly stake/shares."""
import os, sys, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'; ET=ZoneInfo('America/New_York')
SID="1AV_vIsxLIzTivNE_EshZbh-y7QKxLa7MIy1hNJMbAf8"

# ---- hour-of-day weight profile (mean 1; 3-9am ET ~0) from the clean backfill ----
bf=pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet'); bf=bf[bf.counts_main_feed]
ts=pd.to_datetime(bf.ms.to_numpy()//1000,unit='s',utc=True).tz_convert(ET)
span_days=max(1,(bf.ms.max()-bf.ms.min())/86400000)
perhr=pd.Series(0.0,index=range(24))
vc=pd.Series(ts.hour).value_counts()
for h in range(24): perhr[h]=vc.get(h,0)/span_days
weights=(perhr/perhr.mean()).round(3)   # mean 1

def lp(col,bk): return f'INDEX(IFERROR(FILTER(\'_Live_Pacing\'!{col}:{col},\'_Live_Pacing\'!$A:$A="elonmusk",\'_Live_Pacing\'!$B:$B="{bk}")),1)'
def pc(bk):   return f'FILTER(\'_Brackets\'!$G:$G,\'_Brackets\'!$A:$A="elonmusk",\'_Brackets\'!$J:$J="{bk}",\'_Brackets\'!$K:$K="CLOSED")'
def pdur(bk): return f'FILTER(\'_Brackets\'!$I:$I,\'_Brackets\'!$A:$A="elonmusk",\'_Brackets\'!$J:$J="{bk}",\'_Brackets\'!$K:$K="CLOSED")'
def rates(bk):return f'ARRAYFORMULA({pc(bk)}/({pdur(bk)}*24))'
cells={}
def put(a,v): cells[a]=v
put("A1","ELON PACING — LIVE & FORMULA-DRIVEN (auto-updates off _Live_Pacing / _Brackets / _BracketMarkets)")
put("A2","Every number is a formula. _S models = sleep-aware (rate x sleep-adjusted hours; 3-9am ET counts ~0). EV = Model Prob - Yes Price. Max Bid = model fair price. Kelly stake uses live balance.")
put("A3","Balance $"); put("B3","=IFERROR('Dash_V2'!$A$4,0)"); put("C3","Kelly x"); put("D3",0.25); put("E3","Max bet %"); put("F3",0.1)
# hour profile table (shared)
put("N3","ET hr"); put("O3","weight (mean=1)")
for h in range(24): put(f"N{4+h}",h); put(f"O{4+h}",float(weights[h]))
PROF="$N$4:$O$27"
DEFS={"Linear":"Keeps his exact pace so far straight to the deadline. Simplest.",
 "Kalman":"Self-correcting average: usual rate nudged toward current pace, trusting the steadier.",
 "M4MMPP":"Half current pace, half usual pace. A quiet-or-manic hedge.",
 "CurBayes":"Your Bayesian blend: pace-so-far mixed with history by reliability.",
 "M0":"Pools all past auctions + this one into one tweets/hour rate, projected out.",
 "M5NB":"Historical average count, widened for wild weeks. Runs high (weakest).",
 "CONSENSUS":"Median of the 5 models to the left. Bell curve / probs / EV are built on this.",
 "Std":"Wiggle room around consensus. Spreads probability across nearby brackets.",
 "Linear_S":"Sleep-aware Linear: current pace x sleep-adjusted hours left (3-9am ~0).",
 "Kalman_S":"Sleep-aware Kalman: Kalman's rate x sleep-adjusted hours left.",
 "M4MMPP_S":"Sleep-aware MMPP: quiet/manic blended rate x sleep-adjusted hours left."}
LAD=30
def section(base,bk,label):
    r=base+2; OBS=f"$A${r}"; HL=f"$B${r}"; TOT=f"$C${r}"; EL=f"$D${r}"; US=f"$E${r}"; EFF=f"$H${r}"; SL=f"$G${r}"
    CONS=f"$G${base+6}"; STD=f"$H${base+6}"
    put(f"A{base}", f'="ELON {label}:  "&IFERROR({lp("C",bk)},"")')
    for c,t in zip("ABCDEFGH",["Observed","Hours Left","Total h","Elapsed h","Usual rate/h","# priors","Event slug","Eff hrs (sleep)"]): put(f"{c}{base+1}",t)
    put(f"I{r}", f'=IFERROR(LET(s,{lp("D",bk)},DATEVALUE(LEFT(s,10))+TIMEVALUE(MID(s,12,8))-4/24),"")')
    put(f"J{r}", f'=IFERROR(LET(e,{lp("E",bk)},DATEVALUE(LEFT(e,10))+TIMEVALUE(MID(e,12,8))-4/24),"")')
    put(f"A{r}", f'=IFERROR(VALUE({lp("F",bk)}),"")')
    put(f"C{r}", f'=IFERROR((J{r}-I{r})*24,"")')
    put(f"D{r}", f'=IFERROR(MAX(0.01,(NOW()-I{r})*24),"")')
    put(f"B{r}", f'=IFERROR(MAX(0,(J{r}-NOW())*24),"")')
    put(f"E{r}", f'=IFERROR(AVERAGE({rates(bk)}),"")')
    put(f"F{r}", f'=COUNT({pc(bk)})')
    put(f"G{r}", f'=IFERROR(REGEXEXTRACT({lp("G",bk)},"/event/([a-z0-9-]+)"),"")')
    put(f"H{r}", f'=IFERROR(SUMPRODUCT(ARRAYFORMULA(IFERROR(VLOOKUP(MOD(HOUR(NOW())+SEQUENCE(MAX(1,INT(B{r})))-1,24),{PROF},2,FALSE),1))),B{r})')
    labels=["Linear","Kalman","M4MMPP","CurBayes","M0","M5NB","CONSENSUS","Std","Linear_S","Kalman_S","M4MMPP_S"]
    for c,t in zip("ABCDEFGHIJK",labels): put(f"{c}{base+4}",t); put(f"{c}{base+5}",DEFS[t])
    rt=f"VARP({rates(bk)})"
    krate=f'LET(x,{US},P,{rt}+0.01,K,(P+0.01)/(P+0.01+MAX(0.1,P*0.5)),x+K*({OBS}/{EL}-x))'
    put(f"A{base+6}", f'=IFERROR(ROUND({OBS}*{TOT}/{EL},0),"")')
    put(f"B{base+6}", f'=IFERROR(ROUND({OBS}+({krate})*{HL},0),"")')
    put(f"C{base+6}", f'=IFERROR(ROUND({OBS}+(0.5*({OBS}/{EL})+0.5*{US})*{HL},0),"")')
    put(f"D{base+6}", f'=IFERROR(ROUND({lp("I",bk)},0),"")')
    put(f"E{base+6}", f'=IFERROR(ROUND({OBS}+(SUM({pc(bk)})+{OBS})/(SUM(ARRAYFORMULA({pdur(bk)}*24))+{EL})*{HL},0),"")')
    put(f"F{base+6}", f'=IFERROR(ROUND(LET(me,AVERAGE({pc(bk)}),me*(0.7+0.3*(({OBS}/{EL})/(me/{TOT})))),0),"")')
    put(f"G{base+6}", f'=IFERROR(MEDIAN(A{base+6}:E{base+6}),"")')
    put(f"H{base+6}", f'=IFERROR(MAX(1.5,SQRT(MAX({CONS}-{OBS},1))*1.5),"")')
    put(f"I{base+6}", f'=IFERROR(ROUND({OBS}+({OBS}/{EL})*{EFF},0),"")')
    put(f"J{base+6}", f'=IFERROR(ROUND({OBS}+({krate})*{EFF},0),"")')
    put(f"K{base+6}", f'=IFERROR(ROUND({OBS}+(0.5*({OBS}/{EL})+0.5*{US})*{EFF},0),"")')
    h=base+8
    for c,t in zip("ABCDEFGH",["Bracket","Yes Price","Model Prob","Expected Value","Max Bid (fair)","Kelly frac","Stake $","Shares to buy"]): put(f"{c}{h}",t)
    cond=f'\'_BracketMarkets\'!$A:$A={SL}'
    put(f"A{h+1}", f'=IFERROR(FILTER(\'_BracketMarkets\'!$C:$C,{cond}),"")')
    put(f"B{h+1}", f'=IFERROR(FILTER(\'_BracketMarkets\'!$D:$D,{cond}),"")')
    for k in range(LAD):
        rw=h+1+k; A=f"$A{rw}"
        lo=f'IFERROR(VALUE(REGEXEXTRACT({A},"^(\\d+)")),0)'
        hi=f'IF(REGEXMATCH({A},"\\+"),100000,IFERROR(VALUE(REGEXEXTRACT({A},"-(\\d+)")),lo))'
        prob=f'MAX(0,NORMDIST(hi+0.5,{CONS},{STD},1)-NORMDIST(lo-0.5,{CONS},{STD},1))'
        put(f"C{rw}", f'=IF({A}="","",LET(lo,{lo},hi,{hi},ROUND({prob},3)))')
        put(f"D{rw}", f'=IF({A}="","",ROUND(C{rw}-B{rw},3))')
        put(f"E{rw}", f'=IF({A}="","",C{rw})')
        put(f"F{rw}", f'=IF({A}="","",MAX(0,D{rw}/MAX(0.01,1-B{rw}))*$D$3)')
        put(f"G{rw}", f'=IF({A}="","",ROUND(MIN($F$3*$B$3,F{rw}*$B$3),2))')
        put(f"H{rw}", f'=IF({A}="","",IF(B{rw}>0,ROUND(G{rw}/B{rw},0),0))')
section(5,"2DAY","2-DAY")
section(48,"7DAY","7-DAY")
creds=service_account.Credentials.from_service_account_file(os.path.expanduser('~/.claude/google-service-account.json'),
    scopes=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive'],subject='darwin@xagency.com')
sh=build('sheets','v4',credentials=creds)
gid=1954316949
sh.spreadsheets().values().clear(spreadsheetId=SID,range="'Elon Pacing'!A1:Z200").execute()
data=[{'range':f"'Elon Pacing'!{a}",'values':[[v]]} for a,v in cells.items()]
sh.spreadsheets().values().batchUpdate(spreadsheetId=SID,body={'valueInputOption':'USER_ENTERED','data':data}).execute()
print(f"wrote {len(cells)} cells. profile 3-9am weights:", [float(weights[h]) for h in range(3,9)])
PY=0
