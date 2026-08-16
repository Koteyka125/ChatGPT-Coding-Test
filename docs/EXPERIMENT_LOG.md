# Coding-agent experiment log

## Baseline
- Hello World deployed to Render.
- `/count` added and tested.
- GitHub Actions catches intentional application bugs.
- Render API access works through GitHub Actions secret.
- Render deploy status/log inspection works.

## Failure: database test isolation
- PostgreSQL-ready refactor initially caused tests to share data.
- Symptoms: counts included previous tests and task assertions saw old rows.
- Fix: each test now uses a fresh temporary SQLite engine.

## Failure: Render PostgreSQL driver
- Production failed because SQLAlchemy selected the `psycopg2` dialect while `psycopg` was installed.
- Fix: normalize PostgreSQL URLs to `postgresql+psycopg://`.
- Result: Render deployed and data survived a restart.

## Current test
- Add per-user task ownership.
- Verify user A cannot see or modify user B's tasks.
- Measure whether the agent introduces schema/migration/auth regressions.
