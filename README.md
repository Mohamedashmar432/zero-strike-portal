# ZeroStrike Portal

SaaS platform for orchestrating scans from the independent [ZeroStrike Go SAST scanner](../zero-strike-code-scanner), managing projects, API keys, and reports.

See [docs/ZeroStrike_Phase1_Architecture_and_Engineering_Plan.md](docs/ZeroStrike_Phase1_Architecture_and_Engineering_Plan.md) for the full architecture.

## Development

**Backend** (`backend/`, FastAPI + MongoDB/Beanie):
```
cd backend
python -m venv .venv && ./.venv/Scripts/pip install -e ".[dev]"
cp .env.example .env   # set MONGODB_URI to a real MongoDB instance
./.venv/Scripts/uvicorn app.main:app --reload
./.venv/Scripts/pytest   # runs against an in-memory mongomock DB, no real Mongo needed
```

**Frontend** (`frontend/`, Next.js 16 + Tailwind + shadcn/ui):
```
cd frontend
npm install
cp .env.example .env.local
npm run dev
```

**Run both** (two terminals, after the one-time setup above):
```
# terminal 1 — backend on :8000
cd backend && ./.venv/Scripts/uvicorn app.main:app --reload

# terminal 2 — frontend on :3000
cd frontend && npm run dev
```
Then open http://localhost:3000. For cloud scans to actually run (not just queue), set
`SCANNER_BINARY_PATH` in `backend/.env` to a real built `zerostrike`/`zerostrike.exe` —
e.g. the one in the sibling `../zero-strike-code-scanner` repo — otherwise the scanner
subprocess fails with "executable not found".

## Deployment

Single-VM Docker Compose (`deploy/`), with MongoDB Atlas as the only external managed service:
```
cd deploy
cp .env.example .env
cp secrets/mongodb_uri.txt.example secrets/mongodb_uri.txt   # fill in real Atlas URI
cp secrets/jwt_secret.txt.example secrets/jwt_secret.txt     # fill in `openssl rand -hex 32`
docker compose up -d
```
