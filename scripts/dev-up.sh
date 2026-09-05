#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_dir="$project_root/.run"
mkdir -p "$runtime_dir"

if [[ -f "$runtime_dir/api.pid" || -f "$runtime_dir/web.pid" ]]; then
  echo "检测到已有开发服务 PID 文件；请先执行 ./scripts/dev-down.sh" >&2
  exit 1
fi

cd "$project_root"
setsid uv run uvicorn solution_advisor.api.app:app --host 127.0.0.1 --port 8000 \
  >"$runtime_dir/api.log" 2>&1 &
echo $! >"$runtime_dir/api.pid"
setsid npm --prefix frontend run dev >"$runtime_dir/web.log" 2>&1 &
echo $! >"$runtime_dir/web.pid"

for _ in {1..30}; do
  if curl --fail --silent http://127.0.0.1:8000/healthz >/dev/null \
    && curl --fail --silent http://127.0.0.1:5173/ >/dev/null; then
    echo "API:    http://127.0.0.1:8000/"
    echo "Portal: http://127.0.0.1:5173/"
    echo "日志:    .run/api.log 与 .run/web.log"
    exit 0
  fi
  sleep 0.2
done

echo "服务未能启动；请查看 .run/api.log 与 .run/web.log" >&2
"$project_root/scripts/dev-down.sh" || true
exit 1
