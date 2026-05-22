@echo off
echo Setting up EE ^& CS Event Tracker...
echo.

:: Create virtual environment
python -m venv venv
call venv\Scripts\activate.bat

:: Install dependencies
pip install --upgrade pip
pip install -r requirements.txt

:: Install Playwright browsers (needed for JS-heavy sites)
playwright install chromium

:: Initialise the database
python -c "from src.db import init_db; init_db(); print('Database ready.')"

echo.
echo Setup complete!
echo.
echo  Next steps:
echo   1. Run a first scrape:    python runner.py
echo   2. Open the dashboard:    streamlit run dashboard/app.py
echo   3. Start daily scheduler: python scheduler.py
echo.
pause
