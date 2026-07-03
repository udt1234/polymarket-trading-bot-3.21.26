# Registers the daily forward pmxt L2 pull (keeps the archive current for future auctions).
$root = "C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot"
$script = "$root\scripts\pmxt\pmxt_forward.py"
$py = (Get-Command python).Source
$action = New-ScheduledTaskAction -Execute $py -Argument "-u `"$script`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Daily -At 7:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 15) -ExecutionTimeLimit (New-TimeSpan -Hours 6)
Register-ScheduledTask -TaskName "PolymarketPmxtForward" -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "Registered PolymarketPmxtForward (daily 7:00 AM)"
