@echo off
setlocal
title Instalar Admira IA
set "EXE=%~dp0AdmiraIA-Installer.exe"
if exist "%EXE%" (
  start "" "%EXE%"
  exit /b 0
)
set "SCRIPT=%~dp001-Preparar-PC-Admira-IA.ps1"
if not exist "%SCRIPT%" (
  echo No se encontro el instalador de Admira IA.
  echo Extrae todo el contenido del ZIP antes de ejecutarlo.
  pause
  exit /b 2
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" (
  echo.
  echo La instalacion termino con codigo %RESULT%.
  echo Revisa el diagnostico mostrado arriba.
  pause
)
exit /b %RESULT%
