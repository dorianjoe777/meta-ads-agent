@echo off
setlocal
title Meta Ads Agent - Instalador Windows
cd /d "%~dp0"

echo.
echo ===============================================
echo  Meta Ads Agent - Instalacion facil para Windows
echo ===============================================
echo.
echo Este instalador usa Docker Desktop para correr todo:
echo Python, Node, Codex CLI y el dashboard.
echo.

where docker >nul 2>nul
if errorlevel 1 (
  echo No encontre Docker Desktop en este Windows.
  echo.
  echo 1. Instala Docker Desktop:
  echo    https://www.docker.com/products/docker-desktop/
  echo 2. Abre Docker Desktop y espera que diga Running.
  echo 3. Vuelve a hacer doble clic en este archivo.
  echo.
  pause
  exit /b 1
)

if exist "%~dp0scripts\install-from-github.ps1" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-from-github.ps1" -InstallDir "%LOCALAPPDATA%\Meta Ads Agent"
  set "BOOTSTRAP_EXIT=%ERRORLEVEL%"
  if "%BOOTSTRAP_EXIT%"=="0" (
    echo.
    echo Admira IA quedo ejecutandose en segundo plano.
    exit /b 0
  )
  if /I not "%ADMIRA_ALLOW_LOCAL_SOURCE_INSTALL%"=="true" (
    echo.
    echo El instalador protegido no pudo preparar la actualizacion ^(codigo %BOOTSTRAP_EXIT%^).
    echo No voy a iniciar una copia local para evitar reemplazar otra instalacion o sus volumenes.
    echo Revisa la licencia, la conexion y vuelve a ejecutar este instalador.
    pause
    exit /b %BOOTSTRAP_EXIT%
  )
)

if not exist ".env" (
  copy ".env.example" ".env" >nul
  echo Cree el archivo .env para tu configuracion local.
)

echo Construyendo y abriendo el dashboard...
echo Cuando termine, abre: http://127.0.0.1:7871
echo.

docker compose up -d --build
if errorlevel 1 (
  echo No pude iniciar Admira IA con Docker.
  pause
  exit /b 1
)

start "" "http://127.0.0.1:7871/"

echo.
echo Admira IA quedo ejecutandose en segundo plano.
exit /b 0
