@echo off
rem WitMotion Console launcher: starts the engine and opens the browser interface.
rem Close this window (or press Ctrl+C) to stop it and release the serial port.
rem Extra arguments are passed through, e.g.:  start-witmotion.bat --simulate
setlocal
title WitMotion Console
cd /d "%~dp0"
set "URL=http://localhost:8765/"

where python >nul 2>nul
if errorlevel 1 goto :nopython

rem Already running? Just open the browser instead of starting a second copy.
rem (Short connect timeout: Windows takes ~2 s to report a refused localhost port.)
curl.exe -s --connect-timeout 0.5 -m 2 -o nul "http://127.0.0.1:8765/api/status" >nul 2>nul
if not errorlevel 1 goto :running

python -c "import serial" >nul 2>nul
if errorlevel 1 goto :install

:start
echo Starting WitMotion Console...
python -m witmotion serve --data-dir "%~dp0witmotion-data" %*
if errorlevel 1 goto :failed
exit /b 0

:install
echo Installing pyserial...
python -m pip install --user -r requirements.txt
if errorlevel 1 goto :failed
goto :start

:running
echo WitMotion Console is already running. Opening %URL%
start "" "%URL%"
timeout /t 2 >nul
exit /b 0

:nopython
echo Python 3.9 or newer was not found on PATH.
echo Install it from https://www.python.org/downloads/ and run this file again.
pause
exit /b 1

:failed
echo.
echo WitMotion Console stopped with an error. See the messages above.
pause
exit /b 1
