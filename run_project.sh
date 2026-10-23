#!/usr/bin/env bash
set -e

PROJECT_ROOT="/home/qdot/Projects/NoSQL_Project"
cd "$PROJECT_ROOT"

echo "=== 1. Kiểm tra và dọn dẹp các cổng cũ ==="
fuser -k 8000/tcp 2>/dev/null || true
fuser -k 5000/tcp 2>/dev/null || true

echo "=== 2. Kiểm tra Redis Server ==="
if ! redis-cli ping > /dev/null 2>&1; then
    echo "[!] Redis chưa chạy. Đang khởi động redis-server..."
    sudo systemctl start redis-server || redis-server --daemonize yes
fi
echo "[+] Redis Server đang hoạt động tốt (PONG)."

echo "=== 3. Nạp dữ liệu mẫu vào Redis ==="
python3 "$PROJECT_ROOT/backend/seed.py"

echo "=== 4. Khởi động FastAPI Backend (Port 8000) ==="
python3 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
echo "[+] FastAPI đã chạy với PID: $BACKEND_PID"

echo "=== 5. Khởi động Blazor Server Frontend (.NET 10) (Port 5000) ==="
cd "$PROJECT_ROOT/frontend/ChatApp.Frontend"
dotnet run --urls "http://localhost:5000" &
FRONTEND_PID=$!
echo "[+] Blazor Frontend đã chạy với PID: $FRONTEND_PID"

echo ""
echo "=========================================================="
echo " HỆ THỐNG ĐÃ KHỞI ĐỘNG THÀNH CÔNG!"
echo " - FastAPI Backend: http://127.0.0.1:8000"
echo " - Swagger API Docs: http://127.0.0.1:8000/docs"
echo " - Blazor UI Web:   http://localhost:5000"
echo "=========================================================="
echo "Nhấn Ctrl+C để dừng toàn bộ ứng dụng."

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true; exit 0" INT TERM EXIT
wait
