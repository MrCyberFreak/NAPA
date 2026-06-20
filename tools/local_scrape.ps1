<#
  LOCAL mirror of .github/workflows/scrape.yml (the day-after-play cron).

  WHY THIS EXISTS: the GitHub account is over its 2,000-min/month Actions quota
  (shared across all private repos; tripped 2026-06-20, resets ~2026-07-01), so
  the cloud scrape cron is blocked. Until it resets, this runs the SAME capture
  the cloud cron ran, then commits + pushes data/raw as the durable archive.
  When Actions is back, DISABLE/DELETE the "NAPA_DailyScrape" task so the cloud
  cron and this don't both run (double host load).

  HARD host rule (CLAUDE.md): never drive two browser captures at the host at
  once. The historical-backfill campaign (run_backfill.py) also drives the
  browser, so this WAITS while that is running and SKIPS this cycle if it is
  still running after the cap -- the daily capture self-heals via catch-up.

  Run by Scheduled Task "NAPA_DailyScrape" (tools\local_scrape.bat), or manually:
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\local_scrape.ps1
#>
$ErrorActionPreference = 'Continue'
$repo = 'X:\Claude_Code\Projectes\NAPA'
Set-Location $repo

$logDir = Join-Path $repo 'logs\local_scrape'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = (Get-Date).ToString('yyyyMMdd-HHmmss')
$log = Join-Path $logDir "scrape-$stamp.log"
function Log($m) { ("{0}  {1}" -f (Get-Date).ToString('s'), $m) | Tee-Object -FilePath $log -Append }

Log "=== local_scrape start (mirror of scrape.yml) ==="

# --- Host-serialization guard: never run while the historical backfill drives the browser ---
$waited = 0; $capMin = 90
while (Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
       Where-Object { $_.CommandLine -match 'run_backfill\.py' }) {
  if ($waited -ge $capMin) {
    Log "historical-backfill still running after $capMin min -- SKIP this cycle (host rule: one browser at the host). Catch-up will recover it next run."
    Log "=== local_scrape end (skipped) ==="
    exit 0
  }
  Log "historical-backfill (run_backfill.py) is running -- waiting 5 min to honor host-serialization ($waited/$capMin min)"
  Start-Sleep -Seconds 300
  $waited += 5
}

# --- Capture: the exact command the cloud cron ran (scrape all divisions +
#     day-after-play backfill of due divisions + catch-up queue + states.php discovery) ---
Log "capture: python -m src.browser_fetch --scheduled --all-divisions"
python -m src.browser_fetch --scheduled --all-divisions 2>&1 | Tee-Object -FilePath $log -Append
Log "capture exit code: $LASTEXITCODE"

# --- Commit + push data/raw as the durable archive.
#     Identity is passed PER-COMMIT (-c) so this never mutates your git config. ---
git add -A data/raw 2>&1 | Tee-Object -FilePath $log -Append
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
  Log "no archive changes to commit (write-on-change: nothing new)."
} else {
  $today = (Get-Date).ToString('yyyy-MM-dd')
  git -c user.name='napa-archive-bot' -c user.email='napa-archive-bot@users.noreply.github.com' `
      commit -m "chore(archive): local scrape $today [skip ci]" 2>&1 | Tee-Object -FilePath $log -Append
  $pushed = $false
  for ($i = 1; $i -le 5; $i++) {
    git pull --rebase origin main 2>&1 | Tee-Object -FilePath $log -Append
    git push origin HEAD:main 2>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -eq 0) { $pushed = $true; break }
    Log "push race/failure, retry $i/5"
    Start-Sleep -Seconds 5
  }
  if ($pushed) { Log "pushed archive to origin/main." }
  else { Log "PUSH FAILED after 5 retries -- commit is local; will retry next run or push manually." }
}
Log "=== local_scrape end ==="
