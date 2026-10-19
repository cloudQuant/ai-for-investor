@echo off
chcp 65001 >nul
setlocal

if "%~1"=="" goto :usage
set "ACTION=%~1"
if /I not "%ACTION%"=="start" if /I not "%ACTION%"=="stop" if /I not "%ACTION%"=="restart" if /I not "%ACTION%"=="status" if /I not "%ACTION%"=="doctor" goto :usage

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0app.ps1" -Action "%ACTION%"
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%

:usage
echo Usage: scripts\windows\app.bat ^<start^|stop^|restart^|status^|doctor^>
exit /b 2
