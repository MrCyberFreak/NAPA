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
$repo = 'X:\Claude_Code\Projectes\Billiards\NAPA'
Set-Location $repo

$logDir = Join-Path $repo 'logs\local_scrape'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = (Get-Date).ToString('yyyyMMdd-HHmmss')
$log = Join-Path $logDir "scrape-$stamp.log"
function Log($m) { ("{0}  {1}" -f (Get-Date).ToString('s'), $m) | Tee-Object -FilePath $log -Append }

# Run a git command, tee its output to the log, and return git's REAL exit code,
# captured immediately so a following git command can't clobber $LASTEXITCODE
# before we check it. (The original bug wasn't Tee -- Tee-Object is a cmdlet and
# preserves $LASTEXITCODE -- it was that a failed `git add` went unchecked: the
# next line `git diff --cached --quiet` returned 0 for an empty index, which the
# code misread as "nothing to commit.")
function GitStep([string[]]$GitArgs) {
  $out = & git @GitArgs 2>&1
  $code = $LASTEXITCODE
  if ($out) { $out | Tee-Object -FilePath $log -Append | Out-Null }
  return $code
}

# Clear a STALE .git/index.lock (recurs from the IDE git integration). Only when no
# git.exe is running -- never yank the lock out from under a live git process.
function Clear-StaleIndexLock {
  $lock = Join-Path $repo '.git\index.lock'
  if (-not (Test-Path $lock)) { return }
  if (Get-Process git -ErrorAction SilentlyContinue) {
    Log "index.lock present but git.exe is running -- not clearing (will retry)"
    return
  }
  $age = ((Get-Date) - (Get-Item $lock).LastWriteTime).TotalMinutes
  Remove-Item -Force $lock -ErrorAction SilentlyContinue
  Log ("cleared stale .git/index.lock (age {0:N0} min, no git.exe running)" -f $age)
}

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
#     Identity is passed PER-COMMIT (-c) so this never mutates your git config.
#     Self-healing: pre-clear a stale index.lock, check git's REAL exit code at
#     every step, retry the add once on lock failure, distinguish "nothing new"
#     from a FAILED add, and exit non-zero on any failure so the Scheduled Task's
#     LastResult (and napa-scrape-health) surface it instead of reporting success. ---
$archiveFailed = $false
Clear-StaleIndexLock
$addCode = GitStep @('add', '-A', 'data/raw')
if ($addCode -ne 0) {
  Log "git add failed (exit $addCode) -- likely a stale index.lock; clearing and retrying once"
  Clear-StaleIndexLock
  $addCode = GitStep @('add', '-A', 'data/raw')
}
if ($addCode -ne 0) {
  Log "ARCHIVE COMMIT FAILED: git add still failing (exit $addCode). Raw data is captured on disk but UNCOMMITTED -- recover next run or commit manually."
  $archiveFailed = $true
} else {
  git diff --cached --quiet; $hasChanges = ($LASTEXITCODE -ne 0)
  if (-not $hasChanges) {
    Log "no archive changes to commit (write-on-change: nothing new)."
  } else {
    $today = (Get-Date).ToString('yyyy-MM-dd')
    $commitCode = GitStep @('-c', 'user.name=napa-archive-bot',
      '-c', 'user.email=napa-archive-bot@users.noreply.github.com',
      'commit', '-m', "chore(archive): local scrape $today [skip ci]")
    if ($commitCode -ne 0) {
      Log "ARCHIVE COMMIT FAILED: git commit exit $commitCode -- staged but not committed."
      $archiveFailed = $true
    } else {
      $pushed = $false
      for ($i = 1; $i -le 5; $i++) {
        GitStep @('pull', '--rebase', 'origin', 'main') | Out-Null
        $pushCode = GitStep @('push', 'origin', 'HEAD:main')
        if ($pushCode -eq 0) { $pushed = $true; break }
        Log "push race/failure (exit $pushCode), retry $i/5"
        Start-Sleep -Seconds 5
      }
      if ($pushed) { Log "pushed archive to origin/main." }
      else { Log "PUSH FAILED after 5 retries -- commit is LOCAL; will retry next run or push manually."; $archiveFailed = $true }
    }
  }
}

# --- Fold the captured data into napa.db INCREMENTALLY (src/db.py --ingest):
#     idempotent upserts on the EXISTING DB -- no wipe, no profile pass -- so new
#     score sheets / makeups land in seconds and the local DB stays current daily
#     WITHOUT a rebuild. Runs even if the archive commit failed (the raw files are
#     on disk regardless). Tee-Object preserves $LASTEXITCODE, so it's python's
#     real code. ---
$ingestFailed = $false
Log "ingest: python -m src.db --ingest --all-divisions"
python -m src.db --ingest --all-divisions 2>&1 | Tee-Object -FilePath $log -Append
$ingestCode = $LASTEXITCODE
if ($ingestCode -ne 0) {
  Log "INGEST FAILED (exit $ingestCode) -- napa.db NOT updated this run; the raw archive is on disk, re-run 'python -m src.db --ingest --all-divisions' or rebuild."
  $ingestFailed = $true
} else {
  Log "ingest OK -- new score sheets folded into napa.db (no rebuild)."
}

Log "=== local_scrape end ==="
if ($archiveFailed -or $ingestFailed) { exit 1 } else { exit 0 }
