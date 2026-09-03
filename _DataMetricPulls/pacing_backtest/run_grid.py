# -*- coding: utf-8 -*-
"""Driver: run sweep_grid.py across the config matrix (sequential to avoid 16 concurrent pmxt scans),
collect the GRID_RESULT JSON from each, write a ranked table. select{pace,market} x nbrk{2,3} x mode{hold,scalp} x conv{0,6}."""
import subprocess, json, sys, itertools, os
sys.stdout.reconfigure(encoding='utf-8')
HERE=os.path.dirname(os.path.abspath(__file__)); OUT=f"{HERE}/audit_out3"
import pandas as pd
rows=[]
for sel,nb,mode,conv in itertools.product(['pace','market'],[2,3],['hold','scalp'],[0,6]):
    lab=f"{sel}-{nb}-{mode}-c{conv}"
    cfg={'select':sel,'nbrk':nb,'mode':mode,'conv':conv,'label':lab}
    try:
        p=subprocess.run([sys.executable,'-u',f"{HERE}/sweep_grid.py",json.dumps(cfg)],capture_output=True,text=True,timeout=600)
        line=[l for l in p.stdout.splitlines() if l.startswith('GRID_RESULT')]
        if line:
            r=json.loads(line[-1][len('GRID_RESULT '):]); rows.append(r); print(f"done {lab:<22} roi {r['pooled_roi_pct']:>7}%  hit {r['bracket_hit_pct']}%  win {r['win_rate_pct']}%",flush=True)
        else:
            print(f"FAIL {lab}: {p.stderr[-300:]}",flush=True)
    except Exception as ex:
        print(f"ERR {lab}: {ex}",flush=True)
df=pd.DataFrame(rows).sort_values('pooled_roi_pct',ascending=False)
df.to_csv(f"{OUT}/grid_matrix.csv",index=False)
print("\n=== CONFIG GRID (ranked by pooled ROI) ===")
print(df[['label','select','nbrk','mode','conv','n_traded','pooled_roi_pct','win_rate_pct','median_roi_pct','bracket_hit_pct']].to_string(index=False))
print(f"\nWROTE {OUT}/grid_matrix.csv")
