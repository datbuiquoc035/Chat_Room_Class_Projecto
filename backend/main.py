from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import redis
import redis.asyncio as aioredis
import bcrypt
import time
import json
import asyncio

app = FastAPI(title="NoSQL Chat & RateLimiter API", version="1.0.0")

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Redis sync client for standard operations
r = redis.Redis(host='localhost', port=6379, decode_responses=True)

# Rate Limiter settings
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW = 60

@app.middleware("http")
async def rate_limiter_middleware(request: Request, call_next):
    path = request.url.path
    method = request.method
    
    # Classify request into endpoint group
    endpoint_group = None
    group_limit = RATE_LIMIT_MAX

    if path == "/auth/login":
        endpoint_group = "auth"
    elif path == "/rooms" or path == "/rooms/":
        endpoint_group = "rooms"
    elif path.endswith("/messages") and method == "POST":
        endpoint_group = "messages_post"
    elif path.endswith("/join") and method == "POST":
        endpoint_group = "join"
        group_limit = 20
    elif path.startswith("/rooms"):
        endpoint_group = "rooms_read"
        group_limit = 30

    if endpoint_group:
        forwarded = request.headers.get("X-Forwarded-For")
        client_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
        user_id = request.headers.get("X-User-Id") or request.query_params.get("user_id") or request.query_params.get("userId")
        
        identifier = user_id if user_id else client_ip
        current_minute = int(time.time() // RATE_LIMIT_WINDOW)
        key = f"ratelimit:{endpoint_group}:{identifier}:{current_minute}"
        
        try:
            current_count = r.incr(key)
            if current_count == 1:
                r.expire(key, RATE_LIMIT_WINDOW)
            
            ttl = r.ttl(key)
            if ttl < 0:
                ttl = RATE_LIMIT_WINDOW
            
            remaining = max(0, group_limit - current_count)
            
            if current_count > group_limit:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    headers={
                        "Retry-After": str(ttl),
                        "X-RateLimit-Limit": str(group_limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(ttl),
                        "X-RateLimit-Group": endpoint_group
                    },
                    content={
                        "detail": f"Too Many Requests. Rate limit for {endpoint_group} is {group_limit} requests per minute.",
                        "current_requests": current_count,
                        "limit": group_limit,
                        "retry_after": ttl,
                        "group": endpoint_group
                    }
                )
            
            response = await call_next(request)
            response.headers["X-RateLimit-Limit"] = str(group_limit)
            response.headers["X-RateLimit-Remaining"] = str(remaining)
            response.headers["X-RateLimit-Reset"] = str(ttl)
            response.headers["X-RateLimit-Group"] = endpoint_group
            return response
            
        except Exception:
            pass

    return await call_next(request)

# Rate Limit Reset endpoint (for testing/demo)
@app.post("/ratelimit/reset")
def reset_ratelimit():
    keys = r.keys("ratelimit:*")
    if keys:
        r.delete(*keys)
    return {"status": "success", "message": f"Đã xóa thành công {len(keys)} bộ đếm rate limit trong Redis."}

# Pydantic models
class RegisterRequest(BaseModel):
    username: str
    password: str

class LoginRequest(BaseModel):
    username: str
    password: str

class RoomCreate(BaseModel):
    name: str
    owner_id: str

class RoomJoin(BaseModel):
    user_id: str
    username: str = ""

class MessageSend(BaseModel):
    user_id: str
    username: str
    content: str

# Auth endpoints
@app.post("/auth/register")
def register(data: RegisterRequest):
    if r.exists(f"idx:user:{data.username}"):
        raise HTTPException(status_code=400, detail="Username already exists")
    
    uid = f"user_{int(time.time()*1000)}"
    pwd_hash = bcrypt.hashpw(data.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    r.hset(f"user:{uid}", mapping={
        "id": uid,
        "username": data.username,
        "password_hash": pwd_hash,
        "created_at": str(time.time())
    })
    r.set(f"idx:user:{data.username}", uid)
    return {"status": "success", "user_id": uid, "username": data.username}

@app.post("/auth/login")
def login(data: LoginRequest):
    uid = r.get(f"idx:user:{data.username}")
    if not uid:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    
    user_data = r.hgetall(f"user:{uid}")
    if not user_data or not bcrypt.checkpw(data.password.encode('utf-8'), user_data["password_hash"].encode('utf-8')):
        raise HTTPException(status_code=401, detail="Invalid username or password")
        
    return {"status": "success", "user_id": uid, "username": user_data["username"]}

# Room endpoints
@app.get("/rooms")
def list_rooms():
    room_ids = r.smembers("rooms")
    rooms = []
    for rid in room_ids:
        rdata = r.hgetall(f"room:{rid}")
        if rdata:
            rooms.append(rdata)
    rooms.sort(key=lambda x: x.get("id", ""))
    return rooms

@app.get("/rooms/{room_id}")
def get_room(room_id: str):
    if not r.sismember("rooms", room_id):
        raise HTTPException(status_code=404, detail="Room not found")
    rdata = r.hgetall(f"room:{room_id}")
    members = list(r.smembers(f"room:{room_id}:members"))
    rdata["members"] = members
    rdata["member_count"] = len(members)
    return rdata

@app.post("/rooms")
def create_room(data: RoomCreate):
    rid = f"room_{int(time.time()*1000)}"
    r.hset(f"room:{rid}", mapping={
        "id": rid,
        "name": data.name,
        "owner_id": data.owner_id,
        "created_at": str(time.time())
    })
    r.sadd("rooms", rid)
    r.sadd(f"room:{rid}:members", data.owner_id)
    return r.hgetall(f"room:{rid}")

@app.post("/rooms/{room_id}/join")
def join_room(room_id: str, data: RoomJoin):
    if not r.sismember("rooms", room_id):
        raise HTTPException(status_code=404, detail="Room not found")
    
    r.sadd(f"room:{room_id}:members", data.user_id)
    
    if data.username:
        join_msg = {
            "id": f"sys_{int(time.time()*1000)}",
            "room_id": room_id,
            "user_id": "system",
            "username": "Hệ thống",
            "content": f"{data.username} đã tham gia phòng",
            "timestamp": time.time()
        }
        msg_str = json.dumps(join_msg)
        r.rpush(f"room:{room_id}:messages", msg_str)
        r.publish(f"chat:channel:{room_id}", msg_str)

    return {"status": "joined", "room_id": room_id, "user_id": data.user_id}

@app.get("/rooms/{room_id}/messages")
def get_messages(room_id: str, limit: int = 50):
    if not r.sismember("rooms", room_id):
        raise HTTPException(status_code=404, detail="Room not found")
    msgs = r.lrange(f"room:{room_id}:messages", -limit, -1)
    return [json.loads(m) for m in msgs]

@app.post("/rooms/{room_id}/messages")
def send_message(room_id: str, data: MessageSend):
    if not r.sismember("rooms", room_id):
        raise HTTPException(status_code=404, detail="Room not found")
        
    msg = {
        "id": f"msg_{int(time.time()*1000)}",
        "room_id": room_id,
        "user_id": data.user_id,
        "username": data.username,
        "content": data.content,
        "timestamp": time.time()
    }
    msg_str = json.dumps(msg)
    r.rpush(f"room:{room_id}:messages", msg_str)
    r.ltrim(f"room:{room_id}:messages", -100, -1)
    
    # Publish to Redis Pub/Sub channel
    r.publish(f"chat:channel:{room_id}", msg_str)
    return msg

# Non-blocking Async WebSocket Pub/Sub Bridge
@app.websocket("/ws/rooms/{room_id}")
async def websocket_room_endpoint(websocket: WebSocket, room_id: str):
    await websocket.accept()
    async_r = aioredis.Redis(host='localhost', port=6379, decode_responses=True)
    pubsub = async_r.pubsub()
    await pubsub.subscribe(f"chat:channel:{room_id}")
    
    async def listen_redis():
        try:
            async for message in pubsub.listen():
                if message and message.get("type") == "message":
                    data = message.get("data")
                    if data:
                        await websocket.send_text(data)
        except Exception:
            pass

    listen_task = asyncio.create_task(listen_redis())
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        listen_task.cancel()
        try:
            await pubsub.unsubscribe(f"chat:channel:{room_id}")
            await pubsub.close()
            await async_r.close()
        except Exception:
            pass
