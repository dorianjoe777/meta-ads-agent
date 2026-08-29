#!/usr/bin/env bash
set -euo pipefail

# Read-only capacity snapshot. This script never changes swap, containers,
# Compose state, files, or PostgreSQL, and deliberately does not print env.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISK_PATH="${ADMIRA_CAPACITY_DISK_PATH:-$ROOT_DIR}"

printf '%s\n' 'Admira Contabo capacity preflight (read-only)'
if command -v nproc >/dev/null 2>&1; then printf 'cpu_count=%s\n' "$(nproc)"; fi

if command -v free >/dev/null 2>&1; then
  free -b | awk 'NR==1 || NR==2 || NR==3 {print "memory_" tolower($1) "_bytes=" $2 " used_bytes=" $3 " available_bytes=" $7}'
else
  printf '%s\n' 'WARN memory=free command unavailable'
fi
if [[ -r /proc/meminfo ]]; then
  awk '/^(MemTotal|MemAvailable|SwapTotal|SwapFree):/ {key=tolower($1); sub(/:$/, "", key); print "proc_" key "_kb=" $2}' /proc/meminfo
fi

if command -v swapon >/dev/null 2>&1; then
  printf '%s\n' 'swap_devices:'
  # --bytes/--output is not available on all Ubuntu util-linux versions.
  swapon --show 2>/dev/null || printf '%s\n' 'none or unavailable'
fi
if [[ -r /proc/sys/vm/swappiness ]]; then
  printf 'swappiness=%s\n' "$(< /proc/sys/vm/swappiness)"
fi

df -Pk "$DISK_PATH" | awk 'NR==1 {print "disk_header=" $0} NR==2 {print "disk_total_kb=" $2 " disk_used_kb=" $3 " disk_available_kb=" $4 " disk_use=" $5}'

if [[ -r /sys/fs/cgroup/memory.max ]]; then
  printf 'cgroup_version=2\n'
  printf 'cgroup_memory_max=%s\n' "$(< /sys/fs/cgroup/memory.max)"
  [[ -r /sys/fs/cgroup/memory.current ]] && printf 'cgroup_memory_current=%s\n' "$(< /sys/fs/cgroup/memory.current)"
  [[ -r /sys/fs/cgroup/memory.events ]] && sed 's/^/cgroup_/' /sys/fs/cgroup/memory.events
elif [[ -r /sys/fs/cgroup/memory/memory.limit_in_bytes ]]; then
  printf 'cgroup_version=1\n'
  printf 'cgroup_memory_limit=%s\n' "$(< /sys/fs/cgroup/memory/memory.limit_in_bytes)"
  [[ -r /sys/fs/cgroup/memory/memory.usage_in_bytes ]] && printf 'cgroup_memory_current=%s\n' "$(< /sys/fs/cgroup/memory/memory.usage_in_bytes)"
else
  printf '%s\n' 'WARN cgroup_memory=unavailable'
fi

if command -v docker >/dev/null 2>&1; then
  printf '%s\n' 'docker_memory_limits_and_rss:'
  if ! docker stats --no-stream --format '{{.Name}}|{{.MemUsage}}|{{.MemPerc}}|{{.CPUPerc}}' 2>/dev/null; then
    printf '%s\n' 'WARN docker_stats=unavailable'
  fi
  printf '%s\n' 'docker_configured_limits_bytes:'
  while IFS= read -r container_id; do
    [[ -n "$container_id" ]] || continue
    docker inspect --format '{{.Name}}|memory={{.HostConfig.Memory}}|memory_swap={{.HostConfig.MemorySwap}}|nano_cpus={{.HostConfig.NanoCpus}}' \
      "$container_id" 2>/dev/null || printf 'WARN docker_inspect=%s\n' "$container_id"
  done < <(docker ps -q 2>/dev/null || true)
else
  printf '%s\n' 'WARN docker=unavailable'
fi

printf '%s\n' 'No capacity settings were changed.'
