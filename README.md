# Ureshii-Partner Backend (FastAPI)

Production-ready FastAPI backend for orchestrating multi-model AI coding workflows (Coder → Debugger → Fixer), with MongoDB persistence, Redis/QStash queue options, and OpenRouter integration via the OpenAI SDK.

- Async end-to-end (Motor, redis.asyncio, OpenAI SDK)
- Queue backends: Redis (default), QStash, or none
- Default processing mode: sync; can be overridden per request
- Structured JSON logging, clear typing, error handling, and retries

## Run Locally
1) Copy env:
cp backend/.env.example backend/.env

2) Edit backend/.env with your real values (do not commit secrets).

3) Install and run:
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload

Worker (if using Redis queue):
python -m app.workers.consumer

## Docker
docker build -t ureshii-backend ./backend
docker run -p 8000:8000 --env-file backend/.env ureshii-backend

## Example Request (Sync)
POST /v1/jobs
{
  "prompt": "Write a Python function for Fibonacci with memoization."
}

## Example Request (Queue)
POST /v1/jobs
{
  "prompt": "Write a Python function for Fibonacci with memoization.",
  "options": { "mode": "queue" }
}

Then poll:
GET /v1/jobs/{job_id}
GET /v1/jobs/{job_id}/result

## Render Deployment
- Use Docker (recommended):
  - Root Directory: backend
  - Dockerfile Path: backend/Dockerfile
  - Health Check Path: /healthz
  - Auto start command via Dockerfile CMD (uvicorn serves on $PORT)

Ensure environment variables are set in Render:
- MONGODB_URI, MONGODB_DB
- OPENROUTER_API_KEY, OPENROUTER_SITE_URL, OPENROUTER_SITE_NAME
- DEFAULT_CODER_MODEL, DEFAULT_DEBUGGER_MODEL, DEFAULT_FIXER_MODEL
- QUEUE_BACKEND (redis|qstash|none), REDIS_URL (rediss for Upstash)
- QSTASH_URL, QSTASH_TOKEN, QSTASH_CURRENT_SIGNING_KEY, QSTASH_NEXT_SIGNING_KEY, QSTASH_DESTINATION_URL
- PROMPT_MAX_CHARS, APP_CORS_ORIGINS, LOG_LEVEL

Security
- QStash verification is enforced fail-closed. Requests without a valid signature will be rejected.

## Notes
- Default models can be overridden per request: options.coder_model, options.debugger_model, options.fixer_model.
- For QStash, set QSTASH_DESTINATION_URL to your public webhook endpoint and optionally enable signature verification.
- MongoDB indexes are created at startup. Ensure your network/firewall allows connections.
