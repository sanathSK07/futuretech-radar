# ADR-0003: Scheduled ingestion runs in GitHub Actions, not a worker/queue

**Status:** Accepted · **Date:** 2026-09-17

## Context

Ingestion and AI analysis are a daily batch of a few hundred documents taking minutes, not a stream. The budget excludes always-on workers. GitHub Actions is free for public repositories on standard runners.

## Decision

A `schedule` workflow runs `radar ingest && radar extract && radar assess` daily, with `workflow_dispatch` for manual runs and a concurrency group to prevent overlap. Secrets are GitHub Actions secrets. The job ends with a backup export.

## Alternatives considered

- **Celery/RQ + Redis worker on Render/Fly:** flexible; rejected as unnecessary infrastructure for a daily batch, and Fly.io no longer offers a free tier for new users.
- **Airflow/Prefect/Dagster:** rejected as heavyweight for one DAG; revisit only if stages need independent retries and backfills at scale.
- **Render cron job:** viable fallback if Actions' schedule delays become a problem.

## Consequences

Known caveats: runs may be delayed during GitHub load peaks; public-repo schedules auto-disable after 60 days without repository activity (a weekly keep-alive commit or any normal development activity prevents this); schedules run from the default branch only; 6-hour job limit is far above need. Pipeline stages must be idempotent so a delayed or re-run job is harmless.
