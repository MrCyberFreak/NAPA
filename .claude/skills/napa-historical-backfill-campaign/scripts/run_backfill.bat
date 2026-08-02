@echo off
REM Local launcher for the NAPA historical-backfill capture campaign.
REM Run by the Windows Scheduled Task "NAPA_HistoricalBackfill" so the capture is
REM independent of any Claude Code session (survives /clear and closing the app).
REM
REM This is a LOCAL python driver ONLY. It MUST NEVER dispatch any GitHub Actions
REM workflow and is NOT a detached bash dispatch loop (the ~7.5h Actions-dispatch
REM incident is the reason for that rule). Capture is serial, single-context,
REM resumable (skips on-disk pages).
REM
REM Optional args: an explicit space-separated did list; default = computed
REM uncaptured-historical set.
cd /d X:\Claude_Code\Projectes\Billiards\NAPA
python .claude\skills\napa-historical-backfill-campaign\scripts\run_backfill.py %*
