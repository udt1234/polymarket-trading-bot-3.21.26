# -*- coding: utf-8 -*-
"""Selector test (Sir OK'd unlocking the model for SELECTION only, 2026-07-08). Same seesaw dip-buy,
2 brackets, hold, no look-ahead, event-driven; ONLY the bracket-picking projection changes. Decisive
metric = bracket_hit% (does any uncapped/burst selector beat the 61% ceiling toward the ~79% break-even?)."""
import subprocess, json, sys, os
import pandas as pd
sys.stdout.reconfigure(encoding='utf-8')
HERE=os.path.dirname(os.path.abspath(__file__)); OUT=f"{HERE}/audit_out3"
SELECTORS=['pace','ens_uncap','cap25','cap3','kalman','accrual','linear','recent','market']
rows=[]
for sel in SELECTORS:
    for nb in (2,3):
        cfg={'select':sel,'nbrk':nb,'mode':'hold','conv':0,'label':f"sel-{sel}-{nb}"}
        try:
            p=subprocess.run([sys.executable,'-u',f"{HERE}/sweep_grid.py",json.dumps(cfg)],capture_output=True,text=True,timeout=600)
            line=[l for l in p.stdout.splitlines() if l.startswith('GRID_RESULT')]
            if line:
                r=json.loads(line[-1][len('GRID_RESULT '):]); rows.append(r)
                print(f"done {sel:<10} nbrk{nb}  hit {r['bracket_hit_pct']:>5}%  roi {r['pooled_roi_pct']:>7}%  win {r['win_rate_pct']}%",flush=True)
            else: print(f"FAIL {sel}-{nb}: {p.stderr[-300:]}",flush=True)
        except Exception as ex: print(f"ERR {sel}-{nb}: {ex}",flush=True)
df=pd.DataFrame(rows).sort_values(['bracket_hit_pct','pooled_roi_pct'],ascending=False)
df.to_csv(f"{OUT}/selector_matrix.csv",index=False)
print("\n=== SELECTOR TEST (ranked by bracket-hit%, then ROI) ===")
print(df[['select','nbrk','n_traded','bracket_hit_pct','pooled_roi_pct','win_rate_pct','median_roi_pct']].to_string(index=False))
print(f"\nbreak-even bracket-hit ~79%. Base 'pace' = 61%. WROTE {OUT}/selector_matrix.csv")
