# -*- coding: utf-8 -*-
"""Deep correlation pass: Q1-Q6. Robust to 3-source fidelity. No emoji prints."""
import pandas as pd, numpy as np, glob, re, io
from pathlib import Path
OUT = Path("_DataMetricPulls/elon_schedule_analysis"); OUT.mkdir(exist_ok=True, parents=True)
buf = io.StringIO()
def p(*a): print(*a); print(*a, file=buf)

files = sorted(glob.glob("_DataMetricPulls/canonical/posts/elonmusk/*.parquet"))
df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True).sort_values("ts_utc").reset_index(drop=True)
df["is_orig"] = ~(df["is_repost"]|df["is_reply"]|df["is_quote"]|df["is_community_repost"])
# logical day cut at 6am ET (mid-sleep); hours_into = hours since 6am ET
shifted = df["ts_et"] - pd.Timedelta(hours=6)
df["lday"] = shifted.dt.date
df["hinto"] = (shifted - shifted.dt.normalize()).dt.total_seconds()/3600.0   # 0..24 from 6am ET
df["etclock"] = (df["hinto"]+6) % 24
RICH = df[df.ts_utc >= "2025-11-01"].copy()   # originals+reposts captured

def corr(a,b):
    a=np.asarray(a,float); b=np.asarray(b,float); m=~(np.isnan(a)|np.isnan(b))
    return np.corrcoef(a[m],b[m])[0,1] if m.sum()>2 else float("nan")

# ============ daily feature table (RICH window) ============
def day_features(d):
    rows=[]
    for ld,g in d.groupby("lday"):
        g=g.sort_values("ts_et")
        if len(g)<3: continue
        hi=g["hinto"].values
        gaps=np.diff(np.sort(g["ts_et"].values).astype("datetime64[s]").astype(float))/60.0
        # sessions: break at >90 min
        order=np.argsort(g["ts_et"].values); t=g["ts_et"].values[order]
        gp=np.diff(t.astype("datetime64[s]").astype(float))/60.0
        nsess=1+int((gp>90).sum())
        # morning(6-12 ET) / afternoon(12-18)/ evening(18-24)/ latenight(0-6)
        ec=g["etclock"].values
        morn=int(((ec>=6)&(ec<12)).sum()); aft=int(((ec>=12)&(ec<18)).sum())
        eve=int(((ec>=18)&(ec<24)).sum()); late=int(((ec>=0)&(ec<6)).sum())
        rows.append(dict(lday=ld,n=len(g),start_hi=hi.min(),end_hi=hi.max(),span=hi.max()-hi.min(),
            start_et=g.sort_values("ts_et")["etclock"].iloc[0], end_et=g.sort_values("ts_et")["etclock"].iloc[-1],
            nsess=nsess, max_gap=(gp.max() if len(gp) else 0), med_gap=(np.median(gp) if len(gp) else 0),
            morn=morn,aft=aft,eve=eve,late=late,
            reposts=int(g.is_repost.sum()),origs=int(g.is_orig.sum()),replies=int(g.is_reply.sum()),quotes=int(g.is_quote.sum())))
    return pd.DataFrame(rows)
F = day_features(RICH)
p("="*70); p("DAILY FEATURE TABLE (RICH window 2025-11-01+)"); p("="*70)
p(f"active days (>=3 posts): {len(F)}   mean posts/day={F.n.mean():.1f} median={F.n.median():.0f}")

# ---------- Q1 start vs end / timezone shift ----------
p("\n"+"="*70); p("Q1 - START vs END / TIMEZONE SHIFT"); p("="*70)
p(f"corr(start_hi, end_hi)   = {corr(F.start_hi,F.end_hi):+.3f}")
p(f"corr(start_hi, span)     = {corr(F.start_hi,F.span):+.3f}")
p(f"corr(end_hi, span)       = {corr(F.end_hi,F.span):+.3f}")
# conditional: P(late end | late start)
late_start = F.start_hi > F.start_hi.quantile(.75)
late_end   = F.end_hi   > F.end_hi.quantile(.75)
p(f"base rate late_end={late_end.mean()*100:.0f}%   P(late_end | late_start)={late_end[late_start].mean()*100:.0f}%")
# timezone-shift days = BOTH start and end shifted same direction by >=2.5h vs medians
ms,me=F.start_hi.median(),F.end_hi.median()
shift_late = ((F.start_hi-ms>2.5)&(F.end_hi-me>2.5))
shift_early= ((ms-F.start_hi>2.5)&(me-F.end_hi>2.5))
p(f"whole-window-shifted days (both move >=2.5h same dir): late {shift_late.mean()*100:.1f}%  early {shift_early.mean()*100:.1f}%  (rest = end-anchored)")
# monthly drift of first/last ET
md=F.copy(); md["ym"]=pd.to_datetime(md.lday).dt.strftime("%Y-%m")
mm=md.groupby("ym").agg(start_et=("start_et","median"),end_et=("end_et","median"),span=("span","median"),n=("n","size"))
p("\nmonthly median first/last ET hour:"); p(mm.to_string())

# ---------- Q2 burst clusters per day ----------
p("\n"+"="*70); p("Q2 - BURST CLUSTERS PER DAY"); p("="*70)
for thr in [60,90,120]:
    ns=[]
    for ld,g in RICH.groupby("lday"):
        if len(g)<3: continue
        t=np.sort(g["ts_et"].values).astype("datetime64[s]").astype(float)
        gp=np.diff(t)/60.0; ns.append(1+int((gp>thr).sum()))
    ns=np.array(ns)
    dist={k:int((ns==k).sum()) for k in range(1,9)}
    p(f"break>{thr:3d}min: mean={ns.mean():.2f} median={np.median(ns):.0f}  P(>=4 clusters)={(ns>=4).mean()*100:.0f}%  dist1..8={[dist[k] for k in range(1,9)]}")
# preferred time blocks: session START hour histogram
sstart=[]
for ld,g in RICH.groupby("lday"):
    g=g.sort_values("ts_et"); t=g["ts_et"].values.astype("datetime64[s]").astype(float)
    if len(t)<3: continue
    idx=[0]+[i for i in range(1,len(t)) if (t[i]-t[i-1])/60.0>90]
    for i in idx: sstart.append(g["etclock"].iloc[i])
sh=pd.Series(sstart); hb=pd.cut(sh,[0,6,9,12,15,18,21,24],right=False,labels=["0-6","6-9","9-12","12-15","15-18","18-21","21-24"])
p("\nsession-start ET-hour blocks (share %): ")
p((hb.value_counts(normalize=True).reindex(["0-6","6-9","9-12","12-15","15-18","18-21","21-24"])*100).round(1).to_string())

# ---------- Q3 conditional cadence / all correlations ----------
p("\n"+"="*70); p("Q3 - CONDITIONAL CADENCE + CORRELATION MATRIX"); p("="*70)
feat=["n","start_hi","end_hi","span","nsess","max_gap","med_gap","morn","aft","eve","late","reposts","origs"]
p("notable daily correlations:")
pairs=[("start_hi","end_hi"),("start_hi","n"),("start_hi","span"),("n","nsess"),("morn","n"),
       ("morn","aft"),("morn","eve"),("aft","eve"),("n","span"),("med_gap","n"),("end_hi","n"),
       ("reposts","origs"),("morn","late")]
for a,b in pairs: p(f"  corr({a:8s},{b:8s}) = {corr(F[a],F[b]):+.3f}")
# heavy-morning -> heavy-day
hm=F.morn>F.morn.quantile(.75); heavy=F.n>F.n.median()
p(f"\nP(heavy day) base={heavy.mean()*100:.0f}%   P(heavy day | heavy morning)={heavy[hm].mean()*100:.0f}%")
p(f"corr(morning posts, rest-of-day posts) = {corr(F.morn, F.aft+F.eve+F.late):+.3f}")
# days ending ~3am ET: cadence
end3=F[(F.end_et>=2)&(F.end_et<=4)]
p(f"\ndays ending 2-4am ET: {len(end3)} ({len(end3)/len(F)*100:.0f}%)  mean posts={end3.n.mean():.1f} vs others {F[~F.index.isin(end3.index)].n.mean():.1f}")
p(f"  their mean sessions={end3.nsess.mean():.2f} span={end3.span.mean():.1f}h")

# ---------- Q4 replies vs main-wall (supabase full-fidelity only) ----------
p("\n"+"="*70); p("Q4 - REPLIES vs MAIN-WALL (full-fidelity window only)"); p("="*70)
sup=df[df.source=="supabase_elon_tweets"].copy()
sup["mainwall"]=sup.is_orig|sup.is_repost|sup.is_quote
dd=sup.groupby("lday").agg(replies=("is_reply","sum"),mainwall=("mainwall","sum"),
     origs=("is_orig","sum"),reposts=("is_repost","sum"),quotes=("is_quote","sum"),tot=("post_id","size"))
dd=dd[dd.tot>=3]
p(f"window {sup.ts_utc.min().date()} -> {sup.ts_utc.max().date()}  active days n={len(dd)}")
p(f"corr(replies, mainwall)        = {corr(dd.replies,dd.mainwall):+.3f}  (user hypothesis: NEGATIVE)")
p(f"corr(replies, origs+reposts)   = {corr(dd.replies,dd.origs+dd.reposts):+.3f}")
p(f"corr(reply_share, mainwall)    = {corr(dd.replies/dd.tot,dd.mainwall):+.3f}")
p(f"corr(replies, total activity)  = {corr(dd.replies,dd.tot):+.3f}")
hi_reply=dd.replies>dd.replies.median()
p(f"mean mainwall on HIGH-reply days={dd.mainwall[hi_reply].mean():.1f} vs LOW-reply days={dd.mainwall[~hi_reply].mean():.1f}")

# ---------- Q6 repost topic scoring ----------
p("\n"+"="*70); p("Q6 - REPOST TOPIC MIX + PER-PARTNER LEAN"); p("="*70)
rt=df[df.is_repost].copy()
rt["partner"]=rt.content_text.fillna("").str.extract(r"^RT @([A-Za-z0-9_]+)")[0]
rt["body"]=rt.content_text.fillna("").str.lower()
TOPICS={
 "politics":r"\b(trump|biden|maga|democrat|republican|gop|senate|congress|election|vote|border|immigrant|woke|left|right|government|doge|deport|fbi|crime)\b",
 "space":r"\b(spacex|starship|falcon|rocket|launch|orbit|mars|starlink|nasa|satellite)\b",
 "tesla_ev":r"\b(tesla|model [sy3x]|cybertruck|ev|autopilot|fsd|robotaxi|optimus|battery|gigafactory)\b",
 "ai_tech":r"\b(grok|ai\b|xai|neuralink|chip|gpu|robot|llm|compute|engineer)\b",
 "crypto":r"\b(doge|bitcoin|crypto|coin|btc)\b",
 "platform_x":r"\b(\bx\b|twitter|free speech|censorship|community note|creator|subscription)\b",
 "media_news":r"\b(media|news|legacy media|journalist|reporter|fake news|propaganda)\b",
}
for tname,pat in TOPICS.items():
    rt[tname]=rt.body.str.contains(pat,regex=True).astype(int)
base={t:rt[t].mean() for t in TOPICS}
p("overall repost topic share (a repost can hit multiple topics):")
for t in TOPICS: p(f"  {t:12s} {base[t]*100:5.1f}%")
p("\nper top-10 partner topic lean (share of THAT partner's reposts; * = >=1.5x base):")
top10=rt.partner.value_counts().head(10).index
hdr="  partner            "+" ".join(f"{t[:6]:>7s}" for t in TOPICS)
p(hdr)
for ptn in top10:
    sub=rt[rt.partner==ptn]
    cells=[]
    for t in TOPICS:
        v=sub[t].mean(); flag="*" if base[t]>0 and v>=1.5*base[t] else " "
        cells.append(f"{v*100:5.0f}{flag} ")
    p(f"  @{ptn:16s} "+" ".join(c.strip().rjust(7) for c in cells))

(OUT/"REPORT2.txt").write_text(buf.getvalue(),encoding="utf-8")
F.to_csv(OUT/"daily_features_rich.csv",index=False)
p("\n[wrote REPORT2.txt + daily_features_rich.csv]")
