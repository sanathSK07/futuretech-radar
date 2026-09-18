# ADR-0001: Python pipeline/API with a TypeScript web app

**Status:** Accepted · **Date:** 2026-09-17

## Context

The system has three workloads: a batch ingestion/AI pipeline, a read-mostly JSON API with an admin surface, and a dense data-exploration UI. SK has shipped FastAPI services and a Next.js 15 site before. Budget is ≤ $20/month; time is 6–10 h/week.

## Decision

Python 3.12 for `core`, `pipeline` and `api` (FastAPI, SQLAlchemy 2, Pydantic v2); Next.js 15 with TypeScript for `web`. Monorepo with `uv` and npm workspaces.

## Alternatives considered

- **All-Python (FastAPI + Jinja + HTMX):** simplest deploy; rejected because filtering/search UI and later graph views push toward client-side JS anyway, and the frontend portfolio signal is weaker.
- **All-TypeScript (Next.js + Prisma):** one language; rejected because embedding/ML tooling is weaker in TS and long-running ingestion does not fit Vercel's 5-minute function limit.
- **Streamlit:** fastest to a screen; rejected for URL state, theming and "serious platform" feel.

## Consequences

Two deployables and two toolchains to maintain; in exchange, each workload uses its idiomatic ecosystem and the project demonstrates both backend/AI and frontend competence. Shared contracts are enforced by generating TypeScript types from the FastAPI OpenAPI schema (`openapi-typescript`) in CI.
