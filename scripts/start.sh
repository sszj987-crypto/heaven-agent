#!/bin/bash

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PID_FILE="$ROOT/.pids"
LOG_DIR="$ROOT/log"

mkdir -p "$LOG_DIR"

# 检查是否已在运行
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

echo "===== 启动 Heaven Agent ====="

# 首次运行或依赖清单变化时自动创建/修复环境并安装核心依赖。
python3 "$ROOT/scripts/bootstrap.py" || exit 1

# 启动后端 (FastAPI)
cd "$ROOT"
.venv/bin/python -m uvicorn src.main:app --host 127.0.0.1 --port 8326 >> "$LOG_DIR/backend.log" 2>&1 &
BACKEND_PID=$!
echo "后端已启动 (PID: $BACKEND_PID, port: 8326)，等待就绪..."

# 等待后端健康检查通过（最多 60 秒）
for i in $(seq 1 60); do
    if curl -s http://localhost:8326/ > /dev/null 2>&1; then
        echo "后端就绪 (耗时 ${i}s)"
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "后端启动超时，请检查日志: $LOG_DIR/backend.log"
        exit 1
    fi
    sleep 1
done

# 启动前端 (Next.js)
cd "$ROOT/frontend"
npm run dev -- -p 3326 >> "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "前端已启动 (PID: $FRONTEND_PID, port: 3326, log: $LOG_DIR/frontend.log)"

echo "$BACKEND_PID" > "$PID_FILE"
echo "$FRONTEND_PID" >> "$PID_FILE"

echo ""
echo "===== Heaven Agent 已启动 ====="
echo "  前端: http://localhost:3326"
echo "  后端: http://localhost:8326"
echo "  日志: $LOG_DIR/"
echo "  停止服务: ./scripts/stop.sh"
