# Project state

## Goal
Use this repository to test how far a ChatGPT-driven coding workflow can go with GitHub, GitHub Actions, and Render.

## Working pipeline
- ChatGPT changes code through GitHub.
- Pull requests are used for larger changes.
- GitHub Actions runs tests.
- Render deploys `main` automatically.
- Render API is accessed from GitHub Actions through `RENDER_API_KEY`.
- Render deployment and live health checks are verified from Actions.

## Current app
- Flask web app.
- PostgreSQL on Render via `DATABASE_URL`.
- SQLite is used for isolated tests/local fallback.
- User registration/login/logout exists.
- Tasks are now scoped to the logged-in user on the `feature/auth-users` branch.

## Important test lessons
- Keep tests isolated with a fresh temporary database.
- When changing the database layer, test isolation must be re-checked.
- Render checks must only expect deployments for `main`; feature branches are tested by CI but are not production deployments.

## Experiment rule
Increase complexity step by step. Record real failures, fixes, and manual intervention required. The goal is to find the practical quality/complexity ceiling rather than assume it.
