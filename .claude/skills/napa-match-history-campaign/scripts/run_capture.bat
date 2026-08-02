@echo off
REM Detached launcher for the NAPA match-history capture campaign.
REM Promoted from handoffs/run_capture.bat. Run by the Windows Scheduled Task
REM "NAPA_MatchHistoryCapture" so the capture is independent of any Claude Code
REM session (survives /clear and closing the app). The bash wrapper loops/resumes
REM until complete and logs to handoffs\veterans_first.log.
REM Optional first arg: VET threshold (lifetime_played cutoff), default 200.
cd /d X:\Claude_Code\Projectes\Billiards\NAPA
"C:\Program Files\Git\bin\bash.exe" .claude/skills/napa-match-history-campaign/scripts/capture_veterans_first.sh %1
