#!/bin/bash

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/.pids"
LOG_DIR="$ROOT/log"

# 创建日志目录
mkdir -p "$LOG_DIR"

# 检查是否已在运行（验证 PID 对应的进程是否真实存在）
if [ -f "$PID_FILE" ]; then
    ALIVE=false
    while read -r pid; do
        if kill -0 "$pid" 2>/dev/null; then
            ALIVE=true
            break
        fi
    done < "$PID_FILE"
    if $ALIVE; then
        echo "服务已在运行中 (PID 文件存在: $PID_FILE)"
        echo "请先执行 ./scripts/stop.sh 停止已有服务"
        exit 1
    else
        echo "发现残留 PID 文件，进程已不存在，清理后重新启动"
        rm -f "$PID_FILE"
    fi
fi

echo "===== 启动 VoiceFromHeaven ====="

# 启动后端 (FastAPI)
cd "$ROOT"
python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8326 >> "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "后端已启动 (PID: $BACKEND_PID, port: 8326, log: $LOG_DIR/backend.log)"

# 启动前端 (Next.js)
cd "$ROOT/frontend"
npm run dev -- -p 3326 >> "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "前端已启动 (PID: $FRONTEND_PID, port: 3326, log: $LOG_DIR/frontend.log)"

# 记录 PID（放在最后，确保前面的启动命令都已执行）
echo "$BACKEND_PID" > "$PID_FILE"
echo "$FRONTEND_PID" >> "$PID_FILE"

echo ""
echo "===== VoiceFromHeaven 已启动 ====="
echo "  前端: http://localhost:3326"
echo "  后端: http://localhost:8326"
echo "  日志: $LOG_DIR/"
echo "  PID 文件: $PID_FILE"
echo "  停止服务: ./scripts/stop.sh"
