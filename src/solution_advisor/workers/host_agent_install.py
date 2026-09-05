"""Interactive, idempotent installer for the platform-neutral HostAgent."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml

CONFIG = Path("/etc/solution-advisor/host_agent/config.yaml")
SECRET = Path("/etc/solution-advisor/host_agent/registration-token")
UNIT = Path("/etc/systemd/system/solution-advisor-host-agent.service")
SERVICE = "solution-advisor-host-agent.service"
DEFAULT_URL = "http://127.0.0.1:8080"


def run(*args: str) -> None:
    subprocess.run(args, check=True)


def unit_text() -> str:
    return f"""[Unit]
Description=Solution Advisor HostAgent
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User={os.environ.get('SUDO_USER') or os.environ.get('USER', 'root')}
Group=docker
ExecStart=/opt/solution-advisor/host-agent/venv/bin/solution-advisor-worker-agent --config {CONFIG}
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
"""


def ensure_docker() -> None:
    """Never install a host dependency without an explicit interactive consent."""
    if subprocess.run(["docker", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        return
    consent = input("未发现 Docker；是否安装 docker.io 以运行 HostAgent？[y/N]：").strip().lower()
    if consent not in {"y", "yes"}:
        raise SystemExit("HostAgent 依赖 Docker；用户未授权安装，已停止。")
    run("apt-get", "update"); run("apt-get", "install", "-y", "docker.io")
    run("systemctl", "enable", "--now", "docker.service")


def main() -> None:
    parser = argparse.ArgumentParser(description="安装或安全升级 Solution Advisor HostAgent")
    parser.add_argument("--wheel", required=True, help="待安装的 HostAgent wheel")
    parser.add_argument("--control-plane-url", help="控制面地址；省略时交互输入")
    parser.add_argument("--token-file", help="仅本机可读的 Worker Token 文件")
    parser.add_argument("--token-stdin", action="store_true", help="从标准输入读取 Token，不落临时文件")
    parser.add_argument("--instance-id", default="x5-j6-host")
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("需要 root 权限，请使用 sudo 运行安装命令。")
    ensure_docker()
    previous = yaml.safe_load(CONFIG.read_text()) if CONFIG.exists() else {}
    default = args.control_plane_url or previous.get("control_plane_url", DEFAULT_URL)
    url = args.control_plane_url or input(f"控制面地址 [{default}]：").strip() or default
    wheel = Path(args.wheel).resolve()
    if not wheel.is_file() or (not args.token_file and not args.token_stdin):
        raise SystemExit("wheel 或 Token 输入不存在。")
    token_value = sys.stdin.read().strip() if args.token_stdin else Path(args.token_file).read_text().strip()
    if not token_value:
        raise SystemExit("Worker Token 为空。")
    was_active = subprocess.run(["systemctl", "is-active", "--quiet", SERVICE]).returncode == 0
    if was_active: run("systemctl", "stop", SERVICE)
    run("mkdir", "-p", "/opt/solution-advisor/host-agent")
    venv = Path("/opt/solution-advisor/host-agent/venv")
    if not venv.exists(): run(sys.executable, "-m", "venv", str(venv))
    # A local wheel may retain the same version during an emergency fix; force
    # replacement so an explicit upgrade always updates the installed code.
    run(str(venv / "bin/pip"), "install", "--upgrade", "--force-reinstall", "--no-deps", str(wheel))
    CONFIG.parent.mkdir(parents=True, exist_ok=True)
    config = {**previous, "instance_id": args.instance_id, "control_plane_url": url,
              "registration_token_file": str(SECRET), "worker_type": "host-agent",
              "heartbeat_interval_seconds": 15, "discovery_images": previous.get("discovery_images", []),
              "max_concurrency": previous.get("max_concurrency", 1), "capabilities": previous.get("capabilities", ["static_check", "compile", "board_smoke"]),
              "platform_package_version": previous.get("platform_package_version", "discovery-only")}
    CONFIG.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False))
    SECRET.write_text(token_value + "\n")
    service_user = os.environ.get("SUDO_USER") or os.environ.get("USER", "root")
    import pwd
    uid = pwd.getpwnam(service_user).pw_uid
    os.chown(CONFIG, uid, -1); os.chown(SECRET, uid, -1)
    os.chmod(CONFIG, 0o640); os.chmod(SECRET, 0o600)
    UNIT.write_text(unit_text()); os.chmod(UNIT, 0o644)
    run("systemctl", "daemon-reload"); run("systemctl", "enable", SERVICE); run("systemctl", "restart", SERVICE)
    run("systemctl", "is-active", "--quiet", SERVICE)
    print(f"已安装并运行 {SERVICE}；控制面：{url}；配置：{CONFIG}")


if __name__ == "__main__": main()
