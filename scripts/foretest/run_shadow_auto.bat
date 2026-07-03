@echo off
REM Hands-free shadow foretest: snapshot any live 2-day Elon market near its halfway mark.
REM Scheduled twice daily so the ~14h "40-70% elapsed" window is never missed.
set ROOT=C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot
set PYTHONUTF8=1
cd /d "%ROOT%"
"C:\Python314\python.exe" -W ignore "%ROOT%\scripts\foretest\shadow_foretest.py" --auto >> "%ROOT%\_DataMetricPulls\foretest\auto_run.log" 2>&1
echo --- run finished %DATE% %TIME% --- >> "%ROOT%\_DataMetricPulls\foretest\auto_run.log"
