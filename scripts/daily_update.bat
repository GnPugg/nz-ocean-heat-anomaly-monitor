@echo off
setlocal

set "PROJECT_DIR=C:\Users\puggi\Documents\Gianby\data eng\nz-ocean-heat-anomaly-monitor"
set "PYTHON_EXE=C:\Users\puggi\anaconda3\envs\nzheat\python.exe"

cd /d "%PROJECT_DIR%"

set "PYTHONPATH=%PROJECT_DIR%\src"

if not exist logs mkdir logs

echo =============================== >> logs\daily_update.log
echo Daily update started at %date% %time% >> logs\daily_update.log

"%PYTHON_EXE%" -c "import pandas as pd; from datetime import timedelta; df=pd.read_parquet('data/processed/region_daily_sst_history.parquet'); d=pd.to_datetime(df['date']).max().date() + timedelta(days=1); print(d)" > logs\next_date.txt

set /p TARGET_DATE=<logs\next_date.txt

echo Processing date: %TARGET_DATE% >> logs\daily_update.log

"%PYTHON_EXE%" -m nzheat.pipeline.backfill --start-date %TARGET_DATE% --end-date %TARGET_DATE% --append >> logs\daily_update.log 2>&1

if errorlevel 1 (
    echo Backfill failed. Stopping before analytics/load. >> logs\daily_update.log
    echo Daily update failed at %date% %time% >> logs\daily_update.log
    goto END
)

"%PYTHON_EXE%" -m nzheat.analytics.anomalies >> logs\daily_update.log 2>&1
"%PYTHON_EXE%" -m nzheat.analytics.events >> logs\daily_update.log 2>&1
"%PYTHON_EXE%" -m nzheat.load.load_postgres >> logs\daily_update.log 2>&1

echo Daily update finished at %date% %time% >> logs\daily_update.log

:END
endlocal