#!/bin/bash
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/.pids"

echo "===== 停止 VoiceFromHeaven ====="

# 1. 尝试通过 PID 文件停止
if [ -f "$PID_FILE" ]; then
    while read -r pid; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "停止进程 $pid ..."
            kill "$pid" 2>/dev/null || true
        else
            echo "进程 $pid 已退出"
        fi
    done < "$PID_FILE"
    rm -f "$PID_FILE"
else
    echo "未找到 PID 文件，尝试通过进程名匹配停止..."
fi

# 2. 确保子进程也被清理（无论 PID 文件是否存在）
pkill -f "uvicorn src.main:app" 2>/dev/null && echo "已停止 uvicorn 进程" || true
pkill -f "next dev" 2>/dev/null && echo "已停止 next dev 进程" || true

echo "" > $ROOT/log/backend.log
echo "" > $ROOT/log/frontend.log

echo "===== 已停止 ====="
