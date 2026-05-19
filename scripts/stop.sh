#!/bin/bash
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/.pids"

if [ ! -f "$PID_FILE" ]; then
    echo "未找到运行中的服务 (PID 文件不存在: $PID_FILE)"
    exit 1
fi

echo "===== 停止 VoiceFromHeaven ====="

while read -r pid; do
    if kill -0 "$pid" 2>/dev/null; then
        echo "停止进程 $pid ..."
        kill "$pid" 2>/dev/null || true
    else
        echo "进程 $pid 已退出"
    fi
done < "$PID_FILE"

# 确保子进程也被清理
pkill -f "uvicorn src.main:app" 2>/dev/null || true
pkill -f "next dev" 2>/dev/null || true

rm -f "$PID_FILE"
echo "===== 已停止 ====="
