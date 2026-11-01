@echo off
chcp 65001 >nul
setlocal

if "%~1"=="" goto :usage
call "%~dp0..\windows\app.bat" %*
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%

:usage
echo Usage: scripts\ops\app.bat ^<start^|stop^|restart^|status^|doctor^>
exit /b 0
