#!/usr/bin/env bash
# 服务器一键更新：拉取最新代码 → 同步依赖 → 重启服务
# 用法： bash /home/tang/devplan-ops/deploy/deploy.sh
set -euo pipefail

REPO=/home/tang/devplan-ops
BRANCH=main

cd "$REPO"

echo "==> 确保 MySQL 容器在跑"
if ! sudo -n docker ps --format '{{.Names}}' 2>/dev/null | grep -q '^devplan_mysql$'; then
  sudo -n docker start devplan_mysql && sleep 3
fi

echo "==> 拉取最新代码 ($BRANCH)"
git pull --ff-only origin "$BRANCH"

echo "==> 同步依赖"
if [ ! -x .venv/bin/pip ]; then
  echo "   .venv 不存在，创建中..."
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt

echo "==> 重启服务"
systemctl --user restart devplan-ops.service

sleep 1
systemctl --user --no-pager status devplan-ops.service | head -6

echo "==> 健康检查"
PORT=$(grep -oP 'Environment=PORT=\K[0-9]+' "$REPO/deploy/devplan-ops.service" | head -1)
code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:${PORT}/" || echo 000)
echo "    http://127.0.0.1:${PORT}/  ->  HTTP ${code}"
