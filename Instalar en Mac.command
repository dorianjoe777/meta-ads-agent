#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
clear

echo "==============================================="
echo " Meta Ads Agent - Instalacion facil para Mac"
echo "==============================================="
echo
echo "Este instalador usa Docker Desktop para correr todo:"
echo "Python, Node, Codex CLI y el dashboard."
echo

if ! command -v docker >/dev/null 2>&1; then
  echo "No encontre Docker Desktop en este Mac."
  echo
  echo "1. Instala Docker Desktop:"
  echo "   https://www.docker.com/products/docker-desktop/"
  echo "2. Abre Docker Desktop y espera que diga Running."
  echo "3. Vuelve a hacer doble clic en este archivo."
  echo
  read -r -p "Presiona Enter para cerrar..."
  exit 1
fi

if [ -x "./scripts/install-from-github.sh" ]; then
  # Some macOS download locations allow scripts to be read but block direct
  # execution (EPERM), even after chmod. Run through Bash explicitly.
  if /usr/bin/env bash ./scripts/install-from-github.sh mac "$HOME/Applications/Meta Ads Agent"; then
    echo
    echo "Cuando termine, abre: http://127.0.0.1:7871"
    read -r -p "Presiona Enter para cerrar..."
    exit 0
  else
    bootstrap_exit="$?"
    if [ "$bootstrap_exit" -ne 42 ]; then
      read -r -p "Presiona Enter para cerrar..."
      exit "$bootstrap_exit"
    fi
  fi
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Cree el archivo .env para tu configuracion local."
fi

echo "Construyendo y abriendo el dashboard..."
echo "Cuando termine, abre: http://127.0.0.1:7871"
echo

/usr/bin/env bash ./scripts/run-docker.sh

echo
echo "Si cerraste esta ventana, el dashboard se apago."
read -r -p "Presiona Enter para cerrar..."
