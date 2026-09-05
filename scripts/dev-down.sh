#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="$project_root/.run"

for service in web api; do
  pid_file="$runtime_dir/$service.pid"
  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file")"
    if kill -0 "$pid" 2>/dev/null; then
      kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
      echo "已停止 $service（进程组 $pid）"
    else
      echo "$service 的 PID $pid 已退出"
    fi
    rm -f "$pid_file"
  fi
done

rm -f "$runtime_dir"/*.log
rmdir "$runtime_dir" 2>/dev/null || true
