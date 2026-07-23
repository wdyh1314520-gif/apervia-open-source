@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "VERIFY_PS1=%SCRIPT_DIR%verify_app3.ps1"

if not exist "%VERIFY_PS1%" (
  echo [FAIL] verify_app3.ps1 not found: "%VERIFY_PS1%"
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%VERIFY_PS1%" %*
exit /b %ERRORLEVEL%
