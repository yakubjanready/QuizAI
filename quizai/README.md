# QuizAI — AI Powered Real-Time Quiz Platform

Kahoot-ga o'xshash real vaqt viktorinasi. AI avtomatik savollar generatsiya qiladi.

## Texnologiyalar
- **Backend**: FastAPI + Redis + Groq AI (Llama 3.3)
- **Frontend**: Vanilla HTML/CSS/JS (framework talab qilinmaydi)

---

## Ishga tushirish

### 1. Redis o'rnatish va ishga tushirish

**macOS:**
```bash
brew install redis
brew services start redis
```

**Ubuntu/Debian:**
```bash
sudo apt install redis-server
sudo systemctl start redis
```

**Windows:**
```bash
# WSL yoki Docker ishlatish tavsiya etiladi
docker run -d -p 6379:6379 redis:alpine
```

### 2. Python muhitini sozlash

```bash
cd backend
python -m venv venv
source venv/bin/activate        # macOS/Linux
# venv\Scripts\activate         # Windows

pip install -r requirements.txt
```

### 3. .env faylini yaratish

```bash
cp .env.example .env
# .env faylini oching va AI_API_KEY ni kiriting
```

`.env` fayli:
```
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0
AI_API_KEY=gsk_xxx...   # Groq API kaliti
AI_BASE_URL=https://api.groq.com/openai/v1
AI_MODEL=llama-3.3-70b-versatile
```

> **Groq API kalitini** https://console.groq.com dan bepul oling

### 4. Backendni ishga tushirish

```bash
cd backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Backend ishlayotganini tekshirish:
```
http://localhost:8000/
http://localhost:8000/docs   ← Swagger UI
```

### 5. Frontendni ochish

```bash
# frontend/ papkasidagi index.html ni brauzerda oching
open frontend/index.html     # macOS
xdg-open frontend/index.html # Linux
# Windows: faylni 2x bosib oching
```

---

## API Endpointlar

| Metod | Endpoint | Tavsif |
|-------|----------|--------|
| POST | /rooms | Xona yaratish + AI generatsiya |
| GET | /rooms/{code} | Xona holati |
| GET | /rooms/{code}/questions | Barcha savollar |
| POST | /rooms/{code}/questions | Savol qo'shish |
| PUT | /rooms/{code}/questions/{id} | Savolni tahrirlash |
| DELETE | /rooms/{code}/questions/{id} | Savolni o'chirish |
| POST | /rooms/{code}/join | O'yinchi ulanishi |
| POST | /rooms/{code}/start | O'yinni boshlash |
| GET | /rooms/{code}/current-question | Joriy savol |
| POST | /rooms/{code}/answer | Javob yuborish |
| GET | /rooms/{code}/leaderboard | Reyting |
| POST | /rooms/{code}/next | Keyingi savol |

---

## Test qilish (curl)

```bash
# 1. Xona yaratish
curl -X POST http://localhost:8000/rooms \
  -H "Content-Type: application/json" \
  -d '{"topic": "Python dasturlash", "host_name": "Sardor"}'

# 2. Xona holati
curl http://localhost:8000/rooms/ABCDEF

# 3. O'yinchi ulanishi
curl -X POST http://localhost:8000/rooms/ABCDEF/join \
  -H "Content-Type: application/json" \
  -d '{"player_name": "Kamola"}'

# 4. O'yinni boshlash
curl -X POST http://localhost:8000/rooms/ABCDEF/start

# 5. Joriy savol
curl http://localhost:8000/rooms/ABCDEF/current-question

# 6. Javob yuborish
curl -X POST http://localhost:8000/rooms/ABCDEF/answer \
  -H "Content-Type: application/json" \
  -d '{"player_name": "Kamola", "answer": 0, "question_id": "abc123"}'

# 7. Reyting
curl http://localhost:8000/rooms/ABCDEF/leaderboard
```

---

## Ball tizimi

| Holat | Ball |
|-------|------|
| ≤5 soniya | 100 |
| ≤15 soniya | 75 |
| >15 soniya | 50 |
| Noto'g'ri | 0 |

## Bonus xususiyatlar
- ✅ **Redis keshlash**: Bir xil mavzu 24 soat keshlanadi
- ✅ **Rate limiting**: `X-RateLimit-*` headerlar (5 req/min)
- ✅ **TTL**: Xona 1 soatdan keyin avtomatik o'chadi
