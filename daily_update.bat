@echo off
setlocal

set PROJECT_DIR=C:\Users\puggi\Documents\Gianby\data eng\nz-ocean-heat-anomaly-monitor
set LOG_DIR=%PROJECT_DIR%\logs
set LOG_FILE=%LOG_DIR%\daily_update.log

cd /d "%PROJECT_DIR%"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo =============================== >> "%LOG_FILE%"
echo Daily pipeline started at %date% %time% >> "%LOG_FILE%"

call conda activate nzheat >> "%LOG_FILE%" 2>&1

IF ERRORLEVEL 1 (
    echo Failed to activate conda environment at %date% %time% >> "%LOG_FILE%"
    echo Daily pipeline failed at %date% %time% >> "%LOG_FILE%"
    echo =============================== >> "%LOG_FILE%"
    exit /b 1
)

echo Running scripts\monitoring\run_daily_pipeline.py >> "%LOG_FILE%"

python scripts\monitoring\run_daily_pipeline.py >> "%LOG_FILE%" 2>&1

IF ERRORLEVEL 1 (
    echo run_daily_pipeline.py failed at %date% %time% >> "%LOG_FILE%"
    echo Daily pipeline failed at %date% %time% >> "%LOG_FILE%"
    echo =============================== >> "%LOG_FILE%"
    exit /b 1
)

echo Daily pipeline finished successfully at %date% %time% >> "%LOG_FILE%"
echo =============================== >> "%LOG_FILE%"

endlocal
exit /b 0