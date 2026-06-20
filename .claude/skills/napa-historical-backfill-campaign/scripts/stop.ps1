# stop.ps1 -- SAFE stop of the NAPA historical-backfill capture campaign.
#
# WHY THIS EXISTS (the incident guard): an EARLIER detached driver survived
# TaskStop and kept dispatching GitHub Actions for ~7.5h after the user said stop
# (~11 failed runs, real billing; the user is OVER their Actions billing limit).
# So a safe stop here must verify BOTH:
#   (a) on-disk capture is FROZEN  -- no orphaned local chromium/python still writing
#   (b) NO new Actions exposure    -- no new workflow_dispatch since stop, and all 6
#                                     workflows still disabled_manually
# `schtasks /end` and TaskStop/background-bash do NOT kill the process tree -- they
# orphan the python + chromium, which keep capturing. The ONLY reliable stop is:
# end the task, PowerShell tree-kill, verify on-disk FROZEN, and verify no new gh
# dispatch. This script does all four and EXITS NON-ZERO if any check fails --
# never report "stopped" unless on-disk is frozen AND there is no new gh dispatch.
#
# Usage (from the repo root, via Bash):
#   powershell -NoProfile -ExecutionPolicy Bypass -File \
#     .claude/skills/napa-historical-backfill-campaign/scripts/stop.ps1
#
# Exit codes: 0 = stopped, frozen, no Actions exposure;
#             2 = on-disk count still moving (local orphan alive);
#             3 = a NEW gh workflow_dispatch appeared, or a workflow is enabled.

$ErrorActionPreference = 'Continue'
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$TaskName = 'NAPA_HistoricalBackfill'
Set-Location $RepoRoot

# Count the 3 captured page-types across ALL historical dids: score sheets +
# roster_grid + schedule. Reads the uncaptured-set source of truth, _historical.json.
function Get-CaptureCount {
    $total = 0
    try {
        $hist = (Get-Content (Join-Path $RepoRoot 'data\raw\_historical.json') -Raw |
                 ConvertFrom-Json).historical
        $dids = $hist.PSObject.Properties.Name
    } catch { $dids = @() }
    foreach ($did in $dids) {
        $droot = Join-Path $RepoRoot "data\raw\$did"
        $total += @(Get-ChildItem -Path (Join-Path $droot 'scores\*.html') -Recurse -ErrorAction SilentlyContinue).Count
        $total += @(Get-ChildItem -Path (Join-Path $droot '*\roster_grid.html') -ErrorAction SilentlyContinue).Count
        $total += @(Get-ChildItem -Path (Join-Path $droot '*\schedule.html') -ErrorAction SilentlyContinue).Count
    }
    return $total
}

Write-Host "=== SAFE STOP: $TaskName ==="

# 1. End the scheduled task (necessary, NOT sufficient -- does not kill the tree).
Write-Host "[1/4] schtasks /end /tn $TaskName"
schtasks /end /tn $TaskName 2>&1 | Out-Host

# 2. PowerShell process-tree-kill: this campaign's driver + every headless-chromium
#    child. Filter matches THIS driver (run_backfill / browser_fetch) -- NOT the
#    match-history campaign's capture_veterans driver.
Write-Host "[2/4] PowerShell tree-kill (run_backfill | browser_fetch | chrome-headless-shell)"
$killed = 0
Get-CimInstance Win32_Process | Where-Object {
    ($_.CommandLine -match 'run_backfill|browser_fetch' -and $_.Name -ne 'pwsh.exe') -or
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

# 3. Verify FROZEN: poll the capture count twice, ~30s apart. If it moved, a local
#    orphan is still capturing -- fail loudly (exit 2). Do NOT resume until frozen.
Write-Host "[3/4] verifying capture count is FROZEN (two samples ~30s apart)"
$before = Get-CaptureCount
Write-Host "    sample 1: $before captured files"
Start-Sleep -Seconds 30
$after = Get-CaptureCount
Write-Host "    sample 2: $after captured files"
if ($after -ne $before) {
    Write-Host ""
    Write-Host "STILL MOVING ($before -> $after): a local ORPHAN is still capturing." -ForegroundColor Red
    Write-Host "On-disk count is NOT frozen -- do not report stopped. Re-run stop.ps1." -ForegroundColor Red
    Write-Host "  Get-CimInstance Win32_Process | ? { `$_.Name -match 'python|chrome-headless-shell|bash' } | Select ProcessId,Name,CommandLine"
    exit 2
}

# 4. NEW assertion (the incident was an Actions-dispatch loop): there must be NO
#    new workflow_dispatch since stop, and all 6 workflows must still be disabled.
Write-Host "[4/4] verifying NO GitHub Actions exposure (no new workflow_dispatch; workflows disabled)"
$ghOk = $true
try {
    $disabled = (gh workflow list --all 2>$null) -match 'disabled_manually'
    $enabled  = (gh workflow list --all 2>$null) | Where-Object { $_ -match '\bactive\b' }
    Write-Host "    workflows disabled_manually: $(@($disabled).Count)"
    if (@($enabled).Count -gt 0) {
        Write-Host "    ENABLED workflow(s) present:" -ForegroundColor Red
        $enabled | ForEach-Object { Write-Host "      $_" -ForegroundColor Red }
        $ghOk = $false
    }
    $recentDispatch = gh run list --limit 10 --json event,createdAt,status,workflowName 2>$null |
        ConvertFrom-Json | Where-Object { $_.event -eq 'workflow_dispatch' } |
        Where-Object { ([datetime]$_.createdAt) -gt (Get-Date).ToUniversalTime().AddMinutes(-15) }
    if (@($recentDispatch).Count -gt 0) {
        Write-Host "    NEW workflow_dispatch in last 15 min:" -ForegroundColor Red
        $recentDispatch | ForEach-Object { Write-Host "      $($_.workflowName) $($_.createdAt) $($_.status)" -ForegroundColor Red }
        $ghOk = $false
    } else {
        Write-Host "    no new workflow_dispatch in the last 15 min -- clean"
    }
} catch {
    Write-Host "    WARNING: gh check failed ($($_.Exception.Message)) -- cannot confirm no Actions exposure." -ForegroundColor Yellow
    $ghOk = $false
}
if (-not $ghOk) {
    Write-Host ""
    Write-Host "ACTIONS EXPOSURE: a workflow is enabled or a new dispatch appeared." -ForegroundColor Red
    Write-Host "This is the incident pattern -- do NOT report stopped. Investigate gh runs." -ForegroundColor Red
    exit 3
}

Write-Host ""
Write-Host "STOPPED -- on-disk frozen at $after AND no Actions exposure. Campaign halted." -ForegroundColor Green
exit 0
