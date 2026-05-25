#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
clear || true

echo "==============================================="
echo " Meta Ads Agent - Instalacion facil para Linux"
echo "==============================================="
echo
echo "Este instalador usa Docker para correr todo:"
echo "Python, Node, Codex CLI y el dashboard."
echo

if ! command -v docker >/dev/null 2>&1; then
  echo "No encontre Docker en este Linux."
  echo
  echo "Instala Docker Engine y Docker Compose:"
  echo "https://docs.docker.com/engine/install/"
  echo
  read -r -p "Presiona Enter para cerrar..."
  exit 1
fi

if [ -x "./scripts/install-from-github.sh" ]; then
  if ./scripts/install-from-github.sh linux "$HOME/.local/share/meta-ads-agent"; then
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

./scripts/run-docker.sh

echo
echo "Si cerraste esta ventana, el dashboard se apago."
read -r -p "Presiona Enter para cerrar..."
