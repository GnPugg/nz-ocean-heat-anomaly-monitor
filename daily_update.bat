@echo off
setlocal

cd /d "C:\Users\puggi\Documents\Gianby\data eng\nz-ocean-heat-anomaly-monitor"

if not exist logs mkdir logs

echo =============================== >> logs\daily_update.log
echo Daily update started at %date% %time% >> logs\daily_update.log

call conda activate nzheat

echo Running run_daily_append.py >> logs\daily_update.log
python scripts\run_daily_append.py >> logs\daily_update.log 2>&1

IF %ERRORLEVEL% NEQ 0 (
    echo run_daily_append.py failed at %date% %time% >> logs\daily_update.log
    echo Daily update failed at %date% %time% >> logs\daily_update.log
    echo =============================== >> logs\daily_update.log
    exit /b 1
)

echo Running load_preliminary_postgres.py >> logs\daily_update.log
python scripts\load_preliminary_postgres.py >> logs\daily_update.log 2>&1

IF %ERRORLEVEL% NEQ 0 (
    echo load_preliminary_postgres.py failed at %date% %time% >> logs\daily_update.log
    echo Daily update failed at %date% %time% >> logs\daily_update.log
    echo =============================== >> logs\daily_update.log
    exit /b 1
)

echo Daily update finished at %date% %time% >> logs\daily_update.log
echo =============================== >> logs\daily_update.log

endlocal
exit /b 0