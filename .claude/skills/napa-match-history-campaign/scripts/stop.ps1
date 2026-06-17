# stop.ps1 -- SAFE stop of the NAPA match-history capture campaign.
#
# WHY THIS EXISTS: `schtasks /end` and the background-bash/TaskStop mechanism do
# NOT kill the process tree. They orphan the bash wrapper + python + chromium,
# which keep capturing in roster order and INFLATE the page count (~3 incidents in
# one session). The only reliable stop is: end the task, PowerShell tree-kill, THEN
# verify the disk page count is FROZEN. This script does all three and EXITS
# NON-ZERO if the count is still moving (an orphan is still alive) -- never report
# "stopped" while pages are still being written.
#
# Usage (from the repo root, via Bash):
#   powershell -NoProfile -ExecutionPolicy Bypass -File \
#     .claude/skills/napa-match-history-campaign/scripts/stop.ps1
#
# Exit codes: 0 = stopped and frozen; 2 = page count still moving (orphan alive).

$ErrorActionPreference = 'Continue'
$RepoRoot   = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$Glob       = Join-Path $RepoRoot 'data\raw\profiles\*\match_*.html'
$TaskName   = 'NAPA_MatchHistoryCapture'

function Get-PageCount {
    @(Get-ChildItem -Path $Glob -ErrorAction SilentlyContinue).Count
}

Write-Host "=== SAFE STOP: $TaskName ==="

# 1. End the scheduled task (does NOT kill the tree -- necessary but not sufficient).
Write-Host "[1/3] schtasks /end /tn $TaskName"
schtasks /end /tn $TaskName 2>&1 | Out-Host

# 2. PowerShell process-tree-kill (the exact filter from the handoff).
#    Kills the capture python/bash wrappers and every headless-chromium child.
Write-Host "[2/3] PowerShell tree-kill (capture_veterans | browser_fetch | chrome-headless-shell)"
$killed = 0
Get-CimInstance Win32_Process | Where-Object {
    ($_.CommandLine -match 'capture_veterans|browser_fetch' -and $_.Name -ne 'pwsh.exe') -or
    $_.Name -eq 'chrome-headless-shell.exe'
} | ForEach-Object {
    try {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop
        Write-Host "    killed PID $($_.ProcessId) ($($_.Name))"
        $script:killed++
    } catch {
        Write-Host "    could not kill PID $($_.ProcessId) ($($_.Name)): $($_.Exception.Message)"
    }
}
Write-Host "    $killed process(es) killed"

# 3. Verify FROZEN: poll the page count twice, ~30s apart. If it moved, an orphan
#    is still capturing -- fail loudly. Do NOT relaunch until this passes.
Write-Host "[3/3] verifying page count is FROZEN (two samples ~30s apart)"
$before = Get-PageCount
Write-Host "    sample 1: $before pages"
Start-Sleep -Seconds 30
$after = Get-PageCount
Write-Host "    sample 2: $after pages"

if ($after -ne $before) {
    Write-Host ""
    Write-Host "STILL MOVING ($before -> $after): an ORPHAN is still capturing." -ForegroundColor Red
    Write-Host "Page count is NOT frozen -- do not report stopped." -ForegroundColor Red
    Write-Host "Do NOT relaunch. Re-run stop.ps1, or inspect surviving processes:"
    Write-Host "  Get-CimInstance Win32_Process | ? { `$_.Name -match 'python|chrome-headless-shell|bash' } | Select ProcessId,Name,CommandLine"
    exit 2
}

Write-Host ""
Write-Host "STOPPED -- page count frozen at $after. Campaign is fully halted." -ForegroundColor Green
exit 0
