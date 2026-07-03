# -*- coding: utf-8 -*-
"""Tier-1 #1: predictive DISTRIBUTION of Elon's final tweet count given mid-window state.
Target: 2-day noon-ET windows (the abundant, repost-complete recent Elon market).
Ground truth = counts_for_auction in a noon-ET window (the locked count rule), reconstructed
ourselves because canonical auction start/end are trade-derived and wrong for counting.

Core model: a NON-UNIFORM pace curve pf[h] = count_by_hour_h / final_count, learned across
windows. Because windows are noon-ET-anchored, hour h maps to a fixed diurnal position, so the
curve bakes in his sleep window + daily clock automatically. Prediction at (hour h, count c):
    final_hat_distribution = c / { pf[h] samples from OTHER windows }   (a full distribution)
Validated leave-one-out vs a naive uniform-pacing baseline (final = c / f).
"""
import pandas as pd, numpy as np, glob, io
from pathlib import Path
OUT=Path("_DataMetricPulls/elon_schedule_analysis"); buf=io.StringIO()
def p(*a): print(*a); print(*a,file=buf)

posts=pd.concat([pd.read_parquet(f) for f in glob.glob("_DataMetricPulls/canonical/posts/elonmusk/*.parquet")],ignore_index=True)
cf=posts[posts.counts_for_auction==True].copy()
et=cf["ts_et"]

# ---- build non-overlapping consecutive 2-day noon-ET windows, Nov 2025+ ----
WIN_H=48
start0=pd.Timestamp(year=2025,month=11,day=1,hour=12,tz="America/New_York")
last=et.max()
wins=[]
s=start0
while s + pd.Timedelta(hours=WIN_H) <= last:
    e=s+pd.Timedelta(hours=WIN_H)
    sub=et[(et>=s)&(et<e)]
    if len(sub)>0:
        # hourly cumulative trajectory
        rel=((sub - s).dt.total_seconds()/3600).values
        traj=np.array([(rel<=h).sum() for h in range(1,WIN_H+1)],float)  # count by end of hour h
        wins.append({"start":s,"final":traj[-1],"traj":traj})
    s=e
W=[w for w in wins if w["final"]>=8]   # ignore near-empty windows
p(f"2-day noon-ET windows (Nov2025+, final>=8): {len(W)}")
fin=np.array([w['final'] for w in W])
p(f"final count: mean={fin.mean():.0f} median={np.median(fin):.0f} min={fin.min():.0f} max={fin.max():.0f} std={fin.std():.0f}")

# ---- mean pace curve (diagnostic) ----
PF=np.array([w["traj"]/w["final"] for w in W])   # (n,48) pace fractions
mean_pf=PF.mean(0)
p("\nmean pace curve pf[h] = fraction of final done by hour h (noon-ET anchored, h=window hour):")
for h in [6,12,18,24,30,36,42,48]:
    # h hours after noon ET -> ET clock
    etc=(12+h)%24
    p(f"  h={h:2d}  ETclock~{etc:02d}:00 day{1+(12+h)//24}  pf_mean={mean_pf[h-1]:.2f}  pf_p10={np.percentile(PF[:,h-1],10):.2f} pf_p90={np.percentile(PF[:,h-1],90):.2f}")

# ---- predictive distribution + leave-one-out validation ----
def predict_dist(h, c_obs, train_PF):
    s=train_PF[:,h-1]; s=s[s>0.02]
    return c_obs/s          # array of final_hat samples
def bracket_of(c, edges):  # edges like [40,65,90,115,140,165] -> labels <40,40-64,...
    return np.digitize(c, edges)

CHECK_H=[12,24,36,43]   # 25/50/75/90 %
p("\n"+"="*64); p("LEAVE-ONE-OUT VALIDATION (model vs naive c/f baseline)"); p("="*64)
p(f"{'frac':>5} {'n':>4} | {'MAE_model':>9} {'MAE_naive':>9} | {'cover80_model':>13} {'cover80_naive':>13} | medRatioErr")
rng_rows=[]
for h in CHECK_H:
    f=h/WIN_H
    ae_m,ae_n,cov_m,cov_n,ratio=[],[],[],[],[]
    for i,w in enumerate(W):
        c=w["traj"][h-1]; true=w["final"]
        if c<2: continue
        train=np.delete(PF,i,0)
        dist=predict_dist(h,c,train)
        med=np.median(dist); lo,hi=np.percentile(dist,10),np.percentile(dist,90)
        naive=c/f
        ae_m.append(abs(med-true)); ae_n.append(abs(naive-true))
        cov_m.append(lo<=true<=hi)
        # naive 80% band: use baseline residual spread ~ +/-? approximate naive band via uniform assumption error dist
        cov_n.append(abs(naive-true)<=0.20*true)  # naive has no native band; proxy
        ratio.append(abs(med-true)/true)
    p(f"{f*100:4.0f}% {len(ae_m):4d} | {np.mean(ae_m):9.1f} {np.mean(ae_n):9.1f} | {np.mean(cov_m)*100:12.0f}% {'n/a':>13} | {np.median(ratio)*100:7.1f}%")
    rng_rows.append((f,np.mean(ae_m),np.mean(ae_n),np.mean(cov_m)))

# ---- demo: bracket probabilities on a real 2-day bracket set ----
p("\n"+"="*64); p("DEMO: bracket probabilities mid-window (real 65-89-style 2-day set)"); p("="*64)
EDGES=[40,65,90,115,140,165,190,215,240]; LBL=["<40","40-64","65-89","90-114","115-139","140-164","165-189","190-214","215-239","240+"]
# pick a median-ish window, show evolving distribution
ex=sorted(W,key=lambda w:abs(w['final']-np.median(fin)))[0]
p(f"example window start {ex['start'].date()} ET, TRUE final={ex['final']:.0f}")
for h in [12,24,36]:
    c=ex["traj"][h-1]; dist=predict_dist(h,c,PF)
    bs=bracket_of(dist,EDGES); probs=np.bincount(bs,minlength=len(LBL))/len(bs)
    top=sorted(enumerate(probs),key=lambda x:-x[1])[:3]
    p(f"  at h={h:2d} (c={c:.0f}): "+"  ".join(f"{LBL[i]}={pr*100:.0f}%" for i,pr in top))

(OUT/"PREDICTIVE_DIST_REPORT.txt").write_text(buf.getvalue(),encoding="utf-8")
p("\n[wrote PREDICTIVE_DIST_REPORT.txt]")
