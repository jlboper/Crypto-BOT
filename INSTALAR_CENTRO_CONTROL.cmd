@echo off
setlocal
if not exist "%~dp0Crypto AI Trader.vbs" (
  echo No se encontro Crypto AI Trader.vbs en esta carpeta.
  pause
  exit /b 1
)
wscript.exe "%~dp0Crypto AI Trader.vbs"
endlocal
