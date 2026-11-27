@echo off
setlocal
pushd "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -STA -ExecutionPolicy Bypass -File "%~dp0deploy\Setup-Windows.ps1" -Role Client
set "result=%errorlevel%"
popd
pause
exit /b %result%
