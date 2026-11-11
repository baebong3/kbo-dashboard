@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist .venv (
  python -m venv .venv
  .venv\Scripts\pip install -r requirements.txt
)
REM 예) run.bat --start 2020 --end 2024 --csv
.venv\Scripts\python -m txc run --config config.yaml %*
pause
