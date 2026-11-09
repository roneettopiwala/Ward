# Phase 0: Setup

## Goal
A working skeleton: frontend, backend and database all run locally and talk
to each other. No features yet.

## In scope
- Monorepo layout from CLAUDE.md (web/, api/, pipeline/, docs/)
- docker-compose.yml with:
  - PostGIS image that also has pgvector (or install pgvector in a custom
    Dockerfile), with a named volume for data
  - Redis
- On first start, enable the postgis, vector and pgcrypto extensions
- api/: FastAPI app with
  - settings loaded from .env (database URL, Redis URL)
  - async Postgres connection (asyncpg or SQLAlchemy async)
  - GET /health returning API status, database status (including the
    PostGIS version) and Redis status
  - CORS allowing the local frontend
- web/: Next.js app (TypeScript, Tailwind, App Router) with a single page
  that calls /health and shows the result
- .env.example files for api/ and web/, real .env files gitignored
- .gitignore covering Python, Node, .env files, CLAUDE.md and docs/phases/
- Basic linting: ruff for api/, ESLint for web/
- Commands section in CLAUDE.md updated if anything differs

## Out of scope
- Map, MapLibre, any UI beyond the health check (Phase 1)
- Database tables from the schema (added as phases need them)
- LLM clients, LiteLLM, API keys (Phase 3 onward)
- Deployment (Phase 9)

## Done when
With one `docker compose up -d` and the two dev commands, the web page shows
green statuses for the API, Postgres (with PostGIS version) and Redis.
