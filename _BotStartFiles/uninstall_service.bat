@echo off
echo Removing PolyBot startup task...
schtasks /delete /tn "PolyBot" /f
echo Done. PolyBot will no longer auto-start.
pause
