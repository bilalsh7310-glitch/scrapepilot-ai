@echo off
REM ScrapePilot AI — one-click start on Windows (Python 3.11.9)
cd /d %~dp0
if not exist .venv (
    echo Creating virtual environment...
    py -3.11 -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if not exist .env (
    echo No .env found — copying .env.example (scraping works without a key; AI needs one).
    copy .env.example .env >nul
)
python app.py
pause
