@echo off
REM Local launcher for the daily NAPA scrape mirror (replaces scrape.yml while
REM GitHub Actions is over the monthly minute quota; resets ~2026-07-01).
REM Run by the Windows Scheduled Task "NAPA_DailyScrape", or double-click to run now.
cd /d X:\Claude_Code\Projectes\Billiards\NAPA
powershell -NoProfile -ExecutionPolicy Bypass -File "X:\Claude_Code\Projectes\Billiards\NAPA\tools\local_scrape.ps1"
