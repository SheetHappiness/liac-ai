@echo off
setlocal
cd /d "%~dp0"
if not exist "tools\hub\node_modules\.bin\electron.cmd" (
    echo Install the Hub from this folder with npm ci --prefix tools/hub
    pause
    exit /b 1
)
call "tools\hub\node_modules\.bin\electron.cmd" "tools\hub"
