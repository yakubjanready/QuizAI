import random
import string
import time
import re
import json
import uuid
import httpx
from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Any
import redis as redis_lib
from dotenv import load_dotenv
import os

load_dotenv()

app = FastAPI(title="QuizAI Backend", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
AI_API_KEY = os.getenv("AI_API_KEY")
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.groq.com/openai/v1")
AI_MODEL = os.getenv("AI_MODEL", "llama-3.3-70b-versatile")

try:
    r = redis_lib.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0, decode_responses=True)
    r.ping()
    print("Redis connected OK")
except Exception as e:
    print(f"Redis error: {e}")
    r = None

def get_redis():
    if r is None:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    return r

def gen_code():
    return "".join(random.choices(string.ascii_uppercase, k=6))

class CreateRoomReq(BaseModel):
    topic: str
    host_name: str = "Host"

class JoinReq(BaseModel):
    player_name: str

class AnswerReq(BaseModel):
    player_name: str
    answer: Any
    question_id: str

class QuestionReq(BaseModel):
    type: str
    question: str
    correct_answer: Any
    options: Optional[List[str]] = None

@app.get("/")
def root():
    return {"message": "QuizAI is running", "version": "2.0.0"}

@app.get("/health")
def health():
    try:
        get_redis().ping()
        return {"status": "ok", "redis": True}
    except:
        return {"status": "degraded", "redis": False}

async def ai_generate(topic: str) -> list:
    prompt = f"""Generate exactly 10 quiz questions about: "{topic}"

Return ONLY a valid JSON array. No markdown. No explanation. No code blocks.

Include exactly: 4 MCQ, 3 true_false, 3 open questions.

MCQ format: {{"type":"mcq","question":"...?","options":["A","B","C","D"],"correct_answer":0}}
True/False format: {{"type":"true_false","question":"...","correct_answer":true}}
Open format: {{"type":"open","question":"...?","correct_answer":"answer"}}

ONLY the JSON array."""

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{AI_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {AI_API_KEY}", "Content-Type": "application/json"},
            json={"model": AI_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.7, "max_tokens": 2000},
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]

    clean = re.sub(r"```json|```", "", raw).strip()
    m = re.search(r'\[.*\]', clean, re.DOTALL)
    if m:
        clean = m.group(0)
    return json.loads(clean)

@app.post("/rooms")
async def create_room(body: CreateRoomReq):
    redis = get_redis()
    code = gen_code()
    while redis.exists(f"room:{code}"):
        code = gen_code()

    cache_key = f"cache:topic:{body.topic.lower().strip()}"
    cached = redis.get(cache_key)
    if cached:
        questions = json.loads(cached)
        from_cache = True
    else:
        try:
            questions = await ai_generate(body.topic)
            from_cache = False
            redis.setex(cache_key, 86400, json.dumps(questions))
        except Exception as e:
            raise HTTPException(500, f"AI failed: {e}")

    pipe = redis.pipeline()
    pipe.hset(f"room:{code}", mapping={"status":"waiting","host_name":body.host_name,"topic":body.topic,"created_at":str(time.time())})
    pipe.expire(f"room:{code}", 3600)
    pipe.set(f"current_q:{code}", 0)

    for q in questions:
        qid = str(uuid.uuid4())[:8]
        q["id"] = qid
        qd = {"id":qid,"type":q["type"],"question":q["question"],"correct_answer":json.dumps(q["correct_answer"])}
        if q.get("options"):
            qd["options"] = json.dumps(q["options"])
        pipe.hset(f"question:{code}:{qid}", mapping=qd)
        pipe.rpush(f"questions:{code}", qid)
    pipe.execute()

    return {"room_code":code,"topic":body.topic,"question_count":len(questions),"from_cache":from_cache,"status":"waiting"}

@app.get("/rooms/{code}")
def get_room(code: str):
    redis = get_redis()
    room = redis.hgetall(f"room:{code}")
    if not room:
        raise HTTPException(404, "Room not found")
    return {**room, "player_count": redis.scard(f"players:{code}"), "question_count": redis.llen(f"questions:{code}")}

@app.get("/rooms/{code}/questions")
def get_questions(code: str):
    redis = get_redis()
    if not redis.exists(f"room:{code}"):
        raise HTTPException(404, "Room not found")
    qs = []
    for qid in redis.lrange(f"questions:{code}", 0, -1):
        q = redis.hgetall(f"question:{code}:{qid}")
        if q:
            if "options" in q:
                q["options"] = json.loads(q["options"])
            q["correct_answer"] = json.loads(q["correct_answer"])
            qs.append(q)
    return qs

@app.post("/rooms/{code}/questions")
def add_question(code: str, body: QuestionReq):
    redis = get_redis()
    st = redis.hget(f"room:{code}", "status")
    if not st: raise HTTPException(404, "Room not found")
    if st == "active": raise HTTPException(403, "Game started, cannot edit")
    qid = str(uuid.uuid4())[:8]
    qd = {"id":qid,"type":body.type,"question":body.question,"correct_answer":json.dumps(body.correct_answer)}
    if body.options: qd["options"] = json.dumps(body.options)
    redis.hset(f"question:{code}:{qid}", mapping=qd)
    redis.rpush(f"questions:{code}", qid)
    return {"message":"Question added","id":qid}

@app.put("/rooms/{code}/questions/{qid}")
def update_question(code: str, qid: str, body: QuestionReq):
    redis = get_redis()
    st = redis.hget(f"room:{code}", "status")
    if not st: raise HTTPException(404, "Room not found")
    if st == "active": raise HTTPException(403, "Game started, cannot edit")
    if not redis.exists(f"question:{code}:{qid}"): raise HTTPException(404, "Question not found")
    qd = {"id":qid,"type":body.type,"question":body.question,"correct_answer":json.dumps(body.correct_answer)}
    if body.options: qd["options"] = json.dumps(body.options)
    redis.hset(f"question:{code}:{qid}", mapping=qd)
    return {"message":"Updated"}

@app.delete("/rooms/{code}/questions/{qid}")
def delete_question(code: str, qid: str):
    redis = get_redis()
    st = redis.hget(f"room:{code}", "status")
    if not st: raise HTTPException(404, "Room not found")
    if st == "active": raise HTTPException(403, "Game started, cannot edit")
    redis.delete(f"question:{code}:{qid}")
    redis.lrem(f"questions:{code}", 0, qid)
    return {"message":"Deleted"}

@app.post("/rooms/{code}/join")
def join_room(code: str, body: JoinReq):
    redis = get_redis()
    st = redis.hget(f"room:{code}", "status")
    if not st: raise HTTPException(404, "Room not found")
    if st == "finished": raise HTTPException(400, "Game finished")
    redis.sadd(f"players:{code}", body.player_name)
    redis.zadd(f"leaderboard:{code}", {body.player_name: 0})
    return {"message":f"Welcome {body.player_name}!","status":st}

@app.post("/rooms/{code}/start")
def start_game(code: str):
    redis = get_redis()
    st = redis.hget(f"room:{code}", "status")
    if not st: raise HTTPException(404, "Room not found")
    if st == "active": raise HTTPException(400, "Already started")
    if st == "finished": raise HTTPException(400, "Already finished")
    if redis.llen(f"questions:{code}") < 1: raise HTTPException(400, "Need at least 1 question")
    redis.hset(f"room:{code}", "status", "active")
    redis.set(f"current_q:{code}", 0)
    redis.set(f"q_start_time:{code}", str(time.time()))
    return {"message":"Game started!","first_question_id": redis.lindex(f"questions:{code}", 0)}

@app.get("/rooms/{code}/current-question")
def current_question(code: str):
    redis = get_redis()
    st = redis.hget(f"room:{code}", "status")
    if not st: raise HTTPException(404, "Room not found")
    if st == "waiting": raise HTTPException(400, "Not started")
    if st == "finished": raise HTTPException(400, "Finished")
    idx = int(redis.get(f"current_q:{code}") or 0)
    qid = redis.lindex(f"questions:{code}", idx)
    q = redis.hgetall(f"question:{code}:{qid}")
    elapsed = time.time() - float(redis.get(f"q_start_time:{code}") or time.time())
    out = {"id":q["id"],"type":q["type"],"question":q["question"],"question_number":idx+1,"total_questions":redis.llen(f"questions:{code}"),"elapsed_seconds":round(elapsed,1)}
    if "options" in q: out["options"] = json.loads(q["options"])
    return out

@app.post("/rooms/{code}/answer")
def submit_answer(code: str, body: AnswerReq):
    from fastapi.responses import JSONResponse
    redis = get_redis()
    LIMIT = 5
    rk = f"ratelimit:{code}:{body.player_name}"
    cnt = redis.incr(rk)
    if cnt == 1: redis.expire(rk, 60)
    remaining = max(0, LIMIT - cnt)
    hdrs = {"X-RateLimit-Limit":str(LIMIT),"X-RateLimit-Remaining":str(remaining),"X-RateLimit-Reset":str(int(time.time())+60)}
    if cnt > LIMIT:
        return JSONResponse(429, {"detail":"Rate limit exceeded"}, headers=hdrs)
    st = redis.hget(f"room:{code}", "status")
    if st != "active":
        return JSONResponse(content={"detail":"Game not active"}, status_code=400, headers=hdrs)
    idx = int(redis.get(f"current_q:{code}") or 0)
    akey = f"answered:{code}:{idx}"
    if redis.sismember(akey, body.player_name):
        return JSONResponse(content={"detail":"Already answered"}, status_code=400, headers=hdrs)
    q = redis.hgetall(f"question:{code}:{body.question_id}")
    if not q:
        return JSONResponse(content={"detail":"Question not found"}, status_code=404, headers=hdrs)
    elapsed = time.time() - float(redis.get(f"q_start_time:{code}") or time.time())
    correct = json.loads(q["correct_answer"])
    qtype = q["type"]
    ok = False
    if qtype == "open":
        ok = str(body.answer).strip().lower() == str(correct).strip().lower()
    elif qtype == "true_false":
        if isinstance(body.answer, str):
            ok = (body.answer.lower() in ["true","to'g'ri"]) == correct
        else:
            ok = bool(body.answer) == correct
    elif qtype == "mcq":
        ok = int(body.answer) == int(correct)
    pts = 0
    if ok:
        pts = 100 if elapsed <= 5 else (75 if elapsed <= 15 else 50)
    redis.sadd(akey, body.player_name)
    if pts > 0: redis.zincrby(f"leaderboard:{code}", pts, body.player_name)
    return JSONResponse(content={"correct":ok,"points_earned":pts,"elapsed_seconds":round(elapsed,1),"correct_answer":correct if not ok else None}, headers=hdrs)

@app.get("/rooms/{code}/leaderboard")
def leaderboard(code: str):
    redis = get_redis()
    if not redis.exists(f"room:{code}"): raise HTTPException(404, "Room not found")
    scores = redis.zrevrange(f"leaderboard:{code}", 0, -1, withscores=True)
    return [{"rank":i+1,"player":p,"score":int(s)} for i,(p,s) in enumerate(scores)]

@app.get("/rooms/{code}/players")
def get_players(code: str):
    redis = get_redis()
    if not redis.exists(f"room:{code}"): raise HTTPException(404, "Room not found")
    players = redis.smembers(f"players:{code}")
    return {"players": sorted(list(players)), "count": len(players)}

@app.post("/rooms/{code}/next")
def next_question(code: str):
    redis = get_redis()
    if redis.hget(f"room:{code}", "status") != "active":
        raise HTTPException(400, "Game not active")
    idx = int(redis.get(f"current_q:{code}") or 0)
    total = redis.llen(f"questions:{code}")
    nxt = idx + 1
    if nxt >= total:
        redis.hset(f"room:{code}", "status", "finished")
        return {"game_over":True,"message":"Game finished!"}
    redis.set(f"current_q:{code}", nxt)
    redis.set(f"q_start_time:{code}", str(time.time()))
    redis.delete(f"answered:{code}:{nxt}")
    return {"game_over":False,"question_number":nxt+1,"total_questions":total,"question_id":redis.lindex(f"questions:{code}", nxt)}