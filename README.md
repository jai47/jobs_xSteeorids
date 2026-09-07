# AI Career Copilot — Backend (FastAPI)

FastAPI API + nightly job pipeline for [AI Career Copilot](https://github.com/mishraraaj/jobs_xSteeorids).

| Deploy | Host |
|--------|------|
| This repo | **Railway** (root = repo root; Dockerfile included) |
| Database | **Supabase** Postgres (not Supabase Auth) |
| UI | Separate repo: [jai47/ai-career-copilot](https://github.com/jai47/ai-career-copilot) on **Vercel** |

## Local run

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp ../.env.example .env     # from monorepo; or create .env here
# set DATABASE_URL or DB_* and DASHBOARD_SECRET
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

- Health: http://127.0.0.1:8000/health  
- First user: `POST /auth/setup` or `POST /auth/register`  
- Duplicate email returns **409** `EMAIL_EXISTS`

## Database (Supabase)

1. Create a Supabase project → **Settings → Database**.
2. Runtime (Railway / local): **pooler** URI port **6543**.
3. On API startup, `ensure_schema()` creates any missing tables (`db/bootstrap.py`). Prefer that over `alembic upgrade head` on a **brand-new** empty project (Alembic `0001` + later revisions can roll back on a fresh DB).

Optional one-shot against the **direct** URI (`:5432`):

```bash
DATABASE_URL='postgresql://postgres:<password>@db.<ref>.supabase.co:5432/postgres' \
  python -c "from db.bootstrap import ensure_schema; ensure_schema()"
```

`DATABASE_URL` overrides `DB_*`. Remote hosts get `sslmode=require`. Port `6543` / `pooler.supabase.com` uses `NullPool` (PgBouncer-safe).

## Railway

1. Deploy from this GitHub repo (root directory = repo root).
2. Attach a volume at `/data` for resumes (`RESUME_STORAGE_PATH=/data/resumes`).
3. Keep the service always on (APScheduler runs the nightly pipeline).

### Required env

```env
APP_ENV=production
DASHBOARD_SECRET=<long random, not changeme>
DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:6543/postgres
CORS_ORIGINS=https://your-frontend.vercel.app,https://jobs.spanwrap.com
APP_BASE_URL=https://your-frontend.vercel.app
API_BASE_URL=https://your-api.up.railway.app
RESUME_STORAGE_PATH=/data/resumes
GROQ_API_KEY=   # or another LLM key
```

`APP_ENV=production` refuses to boot if `DASHBOARD_SECRET` is still `changeme`.

## Useful endpoints

| Method | Path | Notes |
|--------|------|--------|
| GET | `/health` | DB connectivity |
| GET | `/auth/status` | `{ "has_users": bool }` |
| POST | `/auth/register` | Create user + token |
| POST | `/auth/login` | Email + password |
| POST | `/pipeline/run` | Manual pipeline (Bearer token) |

## Layout

```
api/          routers + schemas
db/           models, engine, migrations, bootstrap
pipeline/     job sources + scoring stages
services/     auth, notifications, resumes, …
llm/          provider clients (on-demand only)
scheduler.py  APScheduler (pipeline + notification drain)
main.py       FastAPI app
Dockerfile    Railway image (WeasyPrint + Tectonic)
```

Auth is HMAC session tokens (`DASHBOARD_SECRET`) — **not** Supabase Auth.
