#!/bin/bash
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$ROOT/.pids"

# 检查是否已在运行
if [ -f "$PID_FILE" ]; then
    echo "服务已在运行中 (PID 文件存在: $PID_FILE)"
    echo "请先执行 ./stop.sh 停止已有服务"
    exit 1
fi

echo "===== 启动 VoiceFromHeaven ====="

# 启动后端 (FastAPI)
cd "$ROOT"
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
echo "后端已启动 (PID: $BACKEND_PID, port: 8000)"

# 启动前端 (Next.js)
cd "$ROOT/frontend"
npm run dev -- -p 3000 &
FRONTEND_PID=$!
echo "前端已启动 (PID: $FRONTEND_PID, port: 3000)"

# 记录 PID
echo "$BACKEND_PID" > "$PID_FILE"
echo "$FRONTEND_PID" >> "$PID_FILE"

echo ""
echo "===== VoiceFromHeaven 已启动 ====="
echo "  前端: http://localhost:3000"
echo "  后端: http://localhost:8000"
echo "  PID 文件: $PID_FILE"
echo "  停止服务: ./stop.sh"
