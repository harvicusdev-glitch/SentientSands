@echo off
setlocal
echo ===================================================
echo     Sentient Sands - Python Dependencies Setup
echo ===================================================
echo.
echo Installing required python packages (flask, requests)...

cd /d "%~dp0"
python -m pip install -r server\requirements.txt

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Failed to install dependencies!
    echo Please make sure you have installed Python 3.10+ from python.org,
    echo and that you checked the "Add Python to PATH" box during installation.
    echo.
) else (
    echo.
    echo [SUCCESS] Dependencies installed successfully.
    echo You can now play Kenshi!
    echo.
)

pause
