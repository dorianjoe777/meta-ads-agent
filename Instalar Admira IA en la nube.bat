@echo off
setlocal
title Admira IA - Instalador en la nube
cd /d "%~dp0"

if not exist "%~dp0installer\windows\AdmiraCloudInstaller.ps1" (
  echo No se encontro el instalador de nube.
  pause
  exit /b 1
)

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -STA -File "%~dp0installer\windows\AdmiraCloudInstaller.ps1"
if errorlevel 1 (
  echo.
  echo La instalacion no pudo completarse.
  pause
  exit /b 1
)
endlocal
