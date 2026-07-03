# -*- coding: utf-8 -*-
"""Elon posting-schedule analysis. Robust to 3-source fidelity differences.
Outputs markdown + csv artifacts. No emojis (Windows cp1252 console)."""
import pandas as pd, numpy as np, glob, re, io, sys
from pathlib import Path

OUT = Path("_DataMetricPulls/elon_schedule_analysis")
OUT.mkdir(exist_ok=True, parents=True)
buf = io.StringIO()
def p(*a):
    print(*a); print(*a, file=buf)

files = sorted(glob.glob("_DataMetricPulls/canonical/posts/elonmusk/*.parquet"))
df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True).sort_values("ts_utc").reset_index(drop=True)
df["is_orig"] = ~(df["is_repost"]|df["is_reply"]|df["is_quote"]|df["is_community_repost"])

p("="*70); p("DATA INVENTORY"); p("="*70)
p(f"Total captured posts: {len(df):,}  |  span {df.ts_utc.min().date()} -> {df.ts_utc.max().date()}")
for s,g in df.groupby("source"):
    p(f"  {s:28s} n={len(g):6,}  {g.ts_utc.min().date()} -> {g.ts_utc.max().date()}  reposts={int(g.is_repost.sum())} replies={int(g.is_reply.sum())} quotes={int(g.is_quote.sum())}")

# ============================================================
# Q1 — POSTING HOURS / DAILY CLOCK / TIMEZONE
# Robust: hour-of-day SHAPE is stable to missing posts. Use ALL posts,
# cross-check vs originals-only. Detect quiet (sleep) trough -> infer tz.
# ============================================================
p("\n"+"="*70); p("Q1 — DAILY CLOCK + TIMEZONE"); p("="*70)
df["h_utc"] = df.ts_utc.dt.hour + df.ts_utc.dt.minute/60.0
def hour_hist(d, col="ts_utc"):
    h = (d[col].dt.hour).value_counts().reindex(range(24), fill_value=0).sort_index()
    return h/ h.sum()
all_h = hour_hist(df)
orig_h = hour_hist(df[df.is_orig])
# rolling 5h-window minimum on UTC hour -> trough center = biological deep-sleep
def trough_center(share):
    arr = share.values
    best, bi = 1e9, 0
    for start in range(24):
        idx = [(start+k)%24 for k in range(5)]
        s = arr[idx].sum()
        if s < best: best, bi = s, start
    center = (bi+2)%24  # middle of the 5h window
    return bi, center, best
bi, center_utc, troughshare = trough_center(all_h)
p(f"Quiet window (lowest-5h block, UTC): {bi:02d}:00-{(bi+5)%24:02d}:00 UTC  holds only {troughshare*100:.1f}% of daily posts")
for tz,off in [("ET",-4),("CT",-5),("MT",-6),("PT",-7)]:
    c = (center_utc+off)%24
    p(f"   deep-sleep center in {tz}: {c:04.1f}h local")
# Active window = where cumulative coverage 5%..95%
p("\nHour-of-day distribution (UTC) -- ALL vs ORIGINALS-ONLY (share %):")
p("  hUTC :  ALL  ORIG   |  hUTC :  ALL  ORIG")
for r in range(12):
    h2=r+12
    p(f"  {r:02d}:00 : {all_h[r]*100:4.1f} {orig_h[r]*100:4.1f}   |  {h2:02d}:00 : {all_h[h2]*100:4.1f} {orig_h[h2]*100:4.1f}")
corr_shape = np.corrcoef(all_h.values, orig_h.values)[0,1]
p(f"\nShape agreement ALL vs ORIG: r={corr_shape:.3f} (high => repost/reply inclusion doesn't distort the clock)")

# Weekday vs weekend (use ET local hour)
df["h_et"] = df.ts_et.dt.hour
df["dow_et"] = df.ts_et.dt.dayofweek  # 0=Mon
wd = df[df.dow_et<5]; we = df[df.dow_et>=5]
p(f"\nPosts/active-hour weekday vs weekend (ET): weekday n={len(wd):,} weekend n={len(we):,}")
dow_names=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
dow_share = df.dow_et.value_counts().reindex(range(7)).sort_index()
p("By day-of-week (ET, share %): " + "  ".join(f"{dow_names[i]} {dow_share[i]/len(df)*100:.1f}" for i in range(7)))

# Monthly trough drift (timezone / routine drift over time) -- use ALL posts
p("\nMonthly deep-sleep center drift (UTC hour of 5h trough center):")
df["ym"] = df.ts_utc.dt.strftime("%Y-%m")
drift=[]
for ym,g in df.groupby("ym"):
    if len(g)<120: continue
    hh = hour_hist(g)
    _,cc,_ = trough_center(hh)
    drift.append((ym,cc,len(g)))
dd = pd.DataFrame(drift, columns=["month","trough_center_utc","n"])
p(dd.to_string(index=False))
p(f"  trough center UTC: mean={dd.trough_center_utc.mean():.1f}h std={dd.trough_center_utc.std():.1f}h (low std => stable body clock)")

# ============================================================
# Q2 — BURST / INTER-ARRIVAL CONTINUATION FORMULA
# Use the richest-capture continuous window so missed posts don't inflate gaps.
# ============================================================
p("\n"+"="*70); p("Q2 — BURST CLUSTERS / CONTINUATION HAZARD"); p("="*70)
rich = df[df.ts_utc >= "2025-11-01"].copy()   # originals+reposts (xtracker) then full (supabase)
rich = rich.sort_values("ts_utc").reset_index(drop=True)
gaps = rich.ts_utc.diff().dt.total_seconds().div(60).dropna().values  # minutes
gaps = gaps[gaps>=0]
p(f"Window for hazard: 2025-11-01 -> {rich.ts_utc.max().date()}  posts={len(rich):,}  gaps={len(gaps):,}")
p(f"Gap minutes: median={np.median(gaps):.1f}  mean={np.mean(gaps):.1f}  p25={np.percentile(gaps,25):.1f}  p75={np.percentile(gaps,75):.1f}  p90={np.percentile(gaps,90):.1f}")
def S(x):  # survival P(gap > x)
    return (gaps > x).mean()
DONE = 120  # 'done for now' = no post for 2h
p(f"\nCONTINUATION TABLE  (DONE = silence >= {DONE} min)")
p(" silent_so_far | P(post w/in 5m) | P(w/in 15m) | P(w/in 30m) | P(DONE>=2h) | median_more_wait")
rows=[]
for s in [0,1,2,3,5,8,10,15,20,30,45,60,90]:
    Ss=S(s)
    if Ss<=0: continue
    def cond_within(w):
        return max(0.0,(Ss - S(s+w))/Ss)
    pdone = S(DONE)/Ss if s<DONE else 1.0
    # median remaining wait given silent s
    grid=np.arange(s,s+600,1.0)
    surv=np.array([S(x)/Ss for x in grid])
    med_idx=np.argmax(surv<=0.5)
    med_more = (grid[med_idx]-s) if surv[-1]<0.5 else float("nan")
    rows.append((s,cond_within(5),cond_within(15),cond_within(30),pdone,med_more))
    p(f"   {s:4d} min     |   {cond_within(5)*100:5.1f}%      |  {cond_within(15)*100:5.1f}%    |  {cond_within(30)*100:5.1f}%    |   {pdone*100:5.1f}%    |  {med_more:5.1f} min")
pd.DataFrame(rows,columns=["silent_min","p_resume_5m","p_resume_15m","p_resume_30m","p_done_2h","median_more_min"]).to_csv(OUT/"q2_continuation_hazard.csv",index=False)
# burst definition: chain of posts each within 30 min of prior
SESS_GAP=120
rich["new_sess"]=(rich.ts_utc.diff().dt.total_seconds().div(60)>SESS_GAP)|(rich.ts_utc.diff().isna())
rich["sess"]=rich["new_sess"].cumsum()
ss=rich.groupby("sess").agg(n=("post_id","size"),start=("ts_utc","min"),end=("ts_utc","max"))
ss["dur_min"]=(ss.end-ss.start).dt.total_seconds()/60
p(f"\nSessions (break = gap>{SESS_GAP}m): {len(ss):,}  posts/session median={ss.n.median():.0f} mean={ss.n.mean():.1f} max={ss.n.max()}")
p(f"  session duration min: median={ss.dur_min.median():.0f} mean={ss.dur_min.mean():.0f}")
p(f"  share of sessions that are single-post: {(ss.n==1).mean()*100:.1f}%   >=10 posts: {(ss.n>=10).mean()*100:.1f}%")

# ============================================================
# Q3 — SLEEP/WAKE: does start time predict end time / duration?
# Anchor logical day at the deep-sleep trough so a day = one wake cycle.
# Use ALL posts. Local = ET.
# ============================================================
p("\n"+"="*70); p("Q3 — WAKE/SLEEP: START -> END CORRELATION"); p("="*70)
anchor_utc = center_utc  # deep sleep center; cut the day here
d2 = df.copy()
d2["logical_day"] = (d2.ts_utc - pd.Timedelta(hours=anchor_utc)).dt.date
# hours since wake-anchor (0..24), local feel via ET for reporting
d2["h_from_anchor"] = ((d2.ts_utc - pd.to_datetime(d2.logical_day).dt.tz_localize("UTC") - pd.Timedelta(hours=anchor_utc)).dt.total_seconds()/3600)
day = d2.groupby("logical_day").agg(n=("post_id","size"),
        first_utc=("ts_utc","min"), last_utc=("ts_utc","max"))
day = day[day.n>=4]  # real active days only
day["start_h_anchor"]=((day.first_utc - pd.to_datetime(day.index).tz_localize("UTC") - pd.Timedelta(hours=anchor_utc)).dt.total_seconds()/3600)
day["end_h_anchor"]=((day.last_utc - pd.to_datetime(day.index).tz_localize("UTC") - pd.Timedelta(hours=anchor_utc)).dt.total_seconds()/3600)
day["active_span_h"]=(day.last_utc-day.first_utc).dt.total_seconds()/3600
# convert start/end to ET clock hour for human reading
day["start_et"]=day.first_utc.dt.tz_convert("America/New_York").dt.hour + day.first_utc.dt.tz_convert("America/New_York").dt.minute/60
day["end_et"]=day.last_utc.dt.tz_convert("America/New_York").dt.hour + day.last_utc.dt.tz_convert("America/New_York").dt.minute/60
p(f"Active days (>=4 posts): {len(day):,}")
p(f"  first-post ET hour: median={day.start_et.median():.1f}  p25={day.start_et.quantile(.25):.1f} p75={day.start_et.quantile(.75):.1f}")
p(f"  last-post  ET hour: median={day.end_et.median():.1f}  p25={day.end_et.quantile(.25):.1f} p75={day.end_et.quantile(.75):.1f}")
p(f"  active span hrs:   median={day.active_span_h.median():.1f}  mean={day.active_span_h.mean():.1f}")
r_se = np.corrcoef(day.start_h_anchor, day.end_h_anchor)[0,1]
r_sd = np.corrcoef(day.start_h_anchor, day.active_span_h)[0,1]
# regression end ~ start
b1,b0 = np.polyfit(day.start_h_anchor, day.end_h_anchor,1)
p(f"\nHYPOTHESIS TEST: later start -> later end?")
p(f"  corr(start, end)      r={r_se:+.3f}   slope={b1:+.2f} (end shifts {b1:+.2f}h per +1h start)")
p(f"  corr(start, duration) r={r_sd:+.3f}   (negative => later start = shorter day)")
# bucket
day["start_bucket"]=pd.cut(day.start_et,[0,6,9,12,24],labels=["overnight<6","early6-9","mid9-12","late>12"])
bk=day.groupby("start_bucket",observed=True).agg(days=("n","size"),med_end_et=("end_et","median"),med_span=("active_span_h","median"),med_posts=("n","median"))
p(bk.to_string())
day.reset_index()[["logical_day","n","start_et","end_et","active_span_h"]].to_csv(OUT/"q3_daily_windows.csv",index=False)

# ============================================================
# Q4 — RETWEET PARTNERS
# ============================================================
p("\n"+"="*70); p("Q4 — TOP RETWEET PARTNERS"); p("="*70)
rt = df[df.is_repost].copy()
rt["partner"]=rt.content_text.fillna("").str.extract(r"^RT @([A-Za-z0-9_]+)")[0]
got = rt.partner.notna().sum()
p(f"Reposts captured: {len(rt):,}  (window {rt.ts_utc.min().date()} -> {rt.ts_utc.max().date()})  partner-parsed: {got:,} ({got/len(rt)*100:.0f}%)")
top = rt.partner.value_counts().head(25)
p("\nTop 25 retweet partners (all captured reposts):")
for i,(h,c) in enumerate(top.items(),1):
    p(f"  {i:2d}. @{h:20s} {c:4d}  ({c/got*100:.1f}%)")
top.to_csv(OUT/"q4_retweet_partners.csv")
# recent-only (last 90d of data) to see current alliances
recent = rt[rt.ts_utc>=rt.ts_utc.max()-pd.Timedelta(days=90)]
p(f"\nTop 12 partners LAST 90 DAYS of data (n={len(recent)}):")
for i,(h,c) in enumerate(recent.partner.value_counts().head(12).items(),1):
    p(f"  {i:2d}. @{h:20s} {c:4d}")

(OUT/"REPORT.txt").write_text(buf.getvalue(), encoding="utf-8")
p("\n[written artifacts to _DataMetricPulls/elon_schedule_analysis/]")
