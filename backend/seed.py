import time
import json
import bcrypt
import redis

r = redis.Redis(host='localhost', port=6379, decode_responses=True)

def seed_data():
    print("=== [1/3] Flushing Redis Database ===")
    r.flushdb()

    print("=== [2/3] Creating 50 Users (user1 -> user50) ===")
    # Pre-compute one bcrypt hash to speed up seeding 50 users
    hashed_pwd = bcrypt.hashpw("123456".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    pipe = r.pipeline()
    for i in range(1, 51):
        uid = f"user_{i}"
        uname = f"user{i}"
        
        pipe.hset(f"user:{uid}", mapping={
            "id": uid,
            "username": uname,
            "password_hash": hashed_pwd,
            "created_at": str(time.time())
        })
        pipe.set(f"idx:user:{uname}", uid)
    pipe.execute()
    print(" -> 50 users created successfully with password '123456'")

    print("=== [3/3] Creating 15 Chat Rooms & Initial Messages ===")
    pipe = r.pipeline()
    for i in range(1, 16):
        rid = f"room_{i}"
        rname = f"Phòng Chat #{i}"
        owner_id = "user_1"
        
        pipe.hset(f"room:{rid}", mapping={
            "id": rid,
            "name": rname,
            "owner_id": owner_id,
            "created_at": str(time.time())
        })
        pipe.sadd("rooms", rid)
        pipe.sadd(f"room:{rid}:members", owner_id)
        
        # Add initial greeting message
        msg = {
            "id": f"msg_init_{i}",
            "room_id": rid,
            "user_id": owner_id,
            "username": "user1",
            "content": f"Chào mừng bạn đến với {rname}! Hãy bắt đầu trò chuyện.",
            "timestamp": time.time()
        }
        pipe.rpush(f"room:{rid}:messages", json.dumps(msg))
    pipe.execute()
    print(" -> 15 rooms created successfully with initial messages.")

    # Seed Rate Limiter dummy keys for >= 5 IP/User concurrently
    print("=== [Bonus] Seeding Rate Limiter Counters for >= 5 IP/User ===")
    current_minute = int(time.time() // 60)
    test_rates = [
        ("192.168.1.101", 3),   # Normal
        ("192.168.1.102", 7),   # Moderate
        ("192.168.1.103", 9),   # Close to limit
        ("192.168.1.104", 10),  # Reached limit (10)
        ("192.168.1.105", 15),  # Exceeded limit (Blocked 429)
        ("user_5", 12)          # User-based limit (Blocked 429)
    ]
    pipe = r.pipeline()
    for ident, count in test_rates:
        key = f"ratelimit:{ident}:{current_minute}"
        pipe.set(key, count)
        pipe.expire(key, 300)
    pipe.execute()
    print(f" -> Pre-seeded rate limit counters for 5 IPs + 1 User in minute window {current_minute}.")
    print("\n[SUCCESS] Redis Database Seeding Completed!")

if __name__ == "__main__":
    seed_data()
