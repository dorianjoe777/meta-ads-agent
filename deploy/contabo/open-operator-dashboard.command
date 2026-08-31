#!/usr/bin/env bash
set -euo pipefail

# Local convenience launcher. It uses the existing SSH alias/key and never
# handles an operator password or provider credential. Closing this terminal
# closes only the SSH tunnel started here, not the dashboard on the VPS.
if [[ "${1:-}" == "--help" ]]; then
  printf '%s\n' \
    'Abre el panel privado de Admira a través del alias SSH admira-contabo.' \
    'Uso: open-operator-dashboard.command [--help]' \
    'Opcionales: ADMIRA_OPERATOR_SSH_HOST, ADMIRA_OPERATOR_LOCAL_PORT, ADMIRA_OPERATOR_REMOTE_PORT.'
  exit 0
fi
if [[ $# -ne 0 ]]; then
  printf '%s\n' 'Argumento desconocido. Usa --help.' >&2
  exit 2
fi

admira_tunnel_host="${ADMIRA_OPERATOR_SSH_HOST:-admira-contabo}"
admira_local_port="${ADMIRA_OPERATOR_LOCAL_PORT:-8791}"
admira_remote_port="${ADMIRA_OPERATOR_REMOTE_PORT:-8791}"
if [[ ! "$admira_tunnel_host" =~ ^[A-Za-z0-9][A-Za-z0-9._@-]*$ ]]; then
  printf '%s\n' 'El alias SSH no es válido.' >&2
  exit 2
fi
for admira_port_candidate in "$admira_local_port" "$admira_remote_port"; do
  if [[ ! "$admira_port_candidate" =~ ^[0-9]{1,5}$ ]] \
      || (( 10#$admira_port_candidate < 1 || 10#$admira_port_candidate > 65535 )); then
    printf '%s\n' 'Los puertos deben estar entre 1 y 65535.' >&2
    exit 2
  fi
done
for admira_required_tool in ssh curl lsof; do
  command -v "$admira_required_tool" >/dev/null 2>&1 || {
    printf 'Falta el programa requerido: %s\n' "$admira_required_tool" >&2
    exit 1
  }
done

admira_tunnel_pid=''
cleanup_admira_tunnel() {
  if [[ -n "$admira_tunnel_pid" ]]; then
    kill "$admira_tunnel_pid" 2>/dev/null || true
    wait "$admira_tunnel_pid" 2>/dev/null || true
  fi
}
trap cleanup_admira_tunnel EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

ssh -N -T -o BatchMode=yes -o ExitOnForwardFailure=yes \
  -o ConnectTimeout=10 -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
  -L "127.0.0.1:${admira_local_port}:127.0.0.1:${admira_remote_port}" \
  "$admira_tunnel_host" &
admira_tunnel_pid=$!
admira_panel_url="http://127.0.0.1:${admira_local_port}/"
admira_tunnel_ready=false
for admira_attempt in {1..20}; do
  if ! kill -0 "$admira_tunnel_pid" 2>/dev/null; then
    printf '%s\n' 'No se pudo abrir el túnel. Comprueba el alias SSH y que el puerto local esté libre.' >&2
    exit 1
  fi
  # Do not open an unrelated service that already occupied the local port
  # while SSH was still negotiating. The listener must belong to our child.
  if lsof -nP -a -p "$admira_tunnel_pid" -iTCP:"$admira_local_port" -sTCP:LISTEN >/dev/null 2>&1 \
      && curl --noproxy '*' --connect-timeout 1 --max-time 2 --silent --fail \
      --output /dev/null "$admira_panel_url"; then
    admira_tunnel_ready=true
    break
  fi
  sleep 0.5
done
if [[ "$admira_tunnel_ready" != true ]]; then
  printf '%s\n' 'SSH está conectado, pero el panel aún no responde en el VPS.' >&2
  exit 1
fi

printf 'Panel privado: %s\n' "$admira_panel_url"
printf '%s\n' 'Mantén esta ventana abierta mientras usas el panel. Ctrl+C cierra el túnel.'
if [[ "$(uname -s)" == Darwin ]]; then
  open "$admira_panel_url"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$admira_panel_url" >/dev/null 2>&1 || true
fi
wait "$admira_tunnel_pid"
admira_tunnel_pid=''
