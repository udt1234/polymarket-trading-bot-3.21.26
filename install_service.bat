@echo off
echo Installing PolyBot as a Windows startup task...

:: Create scheduled task that runs at logon
schtasks /create /tn "PolyBot" /tr "\"%~dp0start_services.bat\"" /sc onlogon /rl highest /f

echo.
echo Done! PolyBot will auto-start when you log in.
echo To remove: run uninstall_service.bat
echo To start now: run start_services.bat
pause
