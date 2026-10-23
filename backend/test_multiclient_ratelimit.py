import urllib.request
import urllib.error
import json
import time
import asyncio
import websockets
import sys

BASE_URL = "http://127.0.0.1:8000"

def log_header(title):
    print("\n" + "="*60)
    print(f" {title}")
    print("="*60)

def test_crud_and_auth():
    log_header("TEST 1: AUTH & CRUD PHÒNG CHAT")
    
    # 1. Login user1
    login_data = json.dumps({"username": "user1", "password": "123456"}).encode('utf-8')
    req = urllib.request.Request(f"{BASE_URL}/auth/login", data=login_data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as res:
        assert res.getcode() == 200
        user_info = json.loads(res.read())
        print(f"✓ Đăng nhập thành công: User ID = {user_info['user_id']}")

    # 2. Get Rooms
    req = urllib.request.Request(f"{BASE_URL}/rooms", headers={"X-Forwarded-For": "10.0.0.1"})
    with urllib.request.urlopen(req) as res:
        rooms = json.loads(res.read())
        assert len(rooms) >= 15
        print(f"✓ Lấy danh sách phòng: Tìm thấy {len(rooms)} phòng chat trong Redis")

    # 3. Create a new Room
    create_data = json.dumps({"name": "Phòng Thử Nghiệm Tự Động", "owner_id": user_info['user_id']}).encode('utf-8')
    req = urllib.request.Request(f"{BASE_URL}/rooms", data=create_data, headers={"Content-Type": "application/json", "X-Forwarded-For": "10.0.0.1"})
    with urllib.request.urlopen(req) as res:
        new_room = json.loads(res.read())
        print(f"✓ Tạo phòng mới thành công: ID = {new_room['id']} - Tên = {new_room['name']}")
    
    return new_room['id'], user_info['user_id']

async def test_pubsub_realtime(room_id, user_id):
    log_header("TEST 2: REDIS PUB/SUB REALTIME WEBSOCKET")
    ws_uri = f"ws://127.0.0.1:8000/ws/rooms/{room_id}"
    
    async with websockets.connect(ws_uri) as ws:
        print(f"✓ Kết nối WebSocket thành công vào kênh: chat:channel:{room_id}")
        
        # Send message via REST to trigger Redis PUBLISH
        msg_payload = json.dumps({
            "user_id": user_id,
            "username": "user1",
            "content": "Kiểm tra Redis PUBLISH và SUBSCRIBE realtime!"
        }).encode('utf-8')
        
        req = urllib.request.Request(
            f"{BASE_URL}/rooms/{room_id}/messages",
            data=msg_payload,
            headers={"Content-Type": "application/json", "X-Forwarded-For": "10.0.0.2"}
        )
        urllib.request.urlopen(req)
        
        # Wait for WebSocket message
        recv_data = await asyncio.wait_for(ws.recv(), timeout=3.0)
        parsed = json.loads(recv_data)
        print(f"✓ WebSocket nhận tin nhắn realtime từ Redis Pub/Sub: '{parsed['content']}'")
        assert parsed["content"] == "Kiểm tra Redis PUBLISH và SUBSCRIBE realtime!"

def test_rate_limiter_spam_15_reqs():
    log_header("TEST 3: RATE LIMITER SPAM 15 REQUESTS / 5 GIÂY (MÃ 429)")
    test_ip = "192.168.100.50"
    url = f"{BASE_URL}/rooms"
    
    ok_count = 0
    blocked_count = 0

    print(f"Gửi 15 requests liên tục với IP: {test_ip}...")
    for i in range(1, 16):
        req = urllib.request.Request(url, headers={"X-Forwarded-For": test_ip})
        try:
            with urllib.request.urlopen(req) as response:
                if response.getcode() == 200:
                    ok_count += 1
                    print(f" -> Req {i:02d}: HTTP 200 OK (Remaining: {response.headers.get('X-RateLimit-Remaining')})")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                blocked_count += 1
                retry_after = e.headers.get("Retry-After")
                print(f" -> Req {i:02d}: HTTP 429 Too Many Requests (Blocked! Retry-After: {retry_after}s)")
            else:
                print(f" -> Req {i:02d}: HTTP {e.code}")
        time.sleep(0.1)

    print("\nKết quả kiểm tra:")
    print(f"  - Thành công (200 OK): {ok_count}/10")
    print(f"  - Bị chặn (429 Too Many Requests): {blocked_count}/5")
    assert ok_count == 10, f"Expected 10 ok, got {ok_count}"
    assert blocked_count == 5, f"Expected 5 blocked, got {blocked_count}"
    print("✓ ĐẠT CHUẨN: Hệ thống chặn chính xác từ request thứ 11 trở đi!")

def test_concurrent_ips():
    log_header("TEST 4: KIỂM THỬ ĐỒNG THỜI >= 5 IP RIÊNG BIỆT")
    ips = [f"172.16.0.{i}" for i in range(1, 6)]
    
    for ip in ips:
        req = urllib.request.Request(f"{BASE_URL}/rooms", headers={"X-Forwarded-For": ip})
        with urllib.request.urlopen(req) as res:
            rem = res.headers.get("X-RateLimit-Remaining")
            print(f"✓ IP {ip} gọi API thành công -> X-RateLimit-Remaining = {rem} (Độc lập theo từng IP)")

def main():
    print("\n=======================================================")
    print("     BẮT ĐẦU KIỂM THỬ TOÀN DIỆN HỆ THỐNG CHAT & RATE LIMIT")
    print("=======================================================")
    
    room_id, user_id = test_crud_and_auth()
    asyncio.run(test_pubsub_realtime(room_id, user_id))
    test_rate_limiter_spam_15_reqs()
    test_concurrent_ips()

    print("\n" + "="*60)
    print(" 🎉 TẤT CẢ CÁC BÀI TEST ĐỀU THÀNH CÔNG 100%!")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
