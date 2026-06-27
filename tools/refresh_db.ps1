<#
  Bring the LOCAL napa.db current with what the scrape cron has already
  committed -- no browser, no host load. Two steps:

    1. git pull --ff-only   (fetch the cron's committed data/raw archive)
    2. python -m src.db --ingest --all-divisions   (fold it into napa.db)

  WHY THIS EXISTS: the GitHub Actions cron commits the raw HTML archive but NOT
  napa.db (it is gitignored / regenerable), so the local DB drifts a day stale
  after every cron run until something ingests. And a bare `--ingest` only
  covers config.DID -- so the safe refresh is ALWAYS --all-divisions. This wraps
  both into one command so "show me current standings" is never served from
  stale data again.

  Run manually:
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\refresh_db.ps1
#>
$ErrorActionPreference = 'Continue'
$PSNativeCommandUseErrorActionPreference = $false  # native stderr is not fatal
$repo = 'X:\Claude_Code\Projectes\NAPA'
Set-Location $repo
$env:PYTHONUTF8 = '1'

function Log($m) { ("{0}  {1}" -f (Get-Date).ToString('s'), $m) }

# Clear a STALE .git/index.lock (IDE git integration leaves these). Only when no
# git.exe is live -- never yank the lock out from under a running git process.
$lock = Join-Path $repo '.git\index.lock'
if ((Test-Path $lock) -and -not (Get-Process git -ErrorAction SilentlyContinue)) {
  $age = ((Get-Date) - (Get-Item $lock).LastWriteTime).TotalMinutes
  Remove-Item -Force $lock -ErrorAction SilentlyContinue
  Log ("cleared stale .git/index.lock (age {0:N0} min, no git.exe running)" -f $age)
}

Log "pull: git pull --ff-only origin main"
git pull --ff-only origin main
$pullCode = $LASTEXITCODE
if ($pullCode -ne 0) {
  Log "PULL FAILED (exit $pullCode) -- not ingesting (DB would be based on stale archive). Resolve the pull, then re-run."
  exit 1
}

Log "ingest: python -m src.db --ingest --all-divisions"
python -m src.db --ingest --all-divisions
$ingestCode = $LASTEXITCODE
if ($ingestCode -ne 0) {
  Log "INGEST FAILED (exit $ingestCode) -- napa.db may be partially updated; the raw archive is on disk, re-run this script or 'python -m src.db --rebuild' to regenerate."
  exit 1
}

Log "refresh OK -- napa.db is current with the committed archive (all active divisions)."
exit 0
