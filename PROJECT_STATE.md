# Project state

## Goal
Use this repository to test how far a ChatGPT-driven coding workflow can go with GitHub, GitHub Actions, and Render.

## Working pipeline
- ChatGPT changes code through GitHub.
- Pull requests are used for larger changes.
- GitHub Actions runs tests.
- Render deploys `main` automatically.
- Render API is accessed from GitHub Actions through `RENDER_API_KEY`.
- Live changes are manually verified after Render deploys.

## Current app
- Flask web app.
- PostgreSQL on Render via `DATABASE_URL`.
- SQLite is used for isolated tests/local fallback.
- User registration/login/logout with hashed passwords.
- CSRF protection on POST actions.
- User-owned tasks with editing, toggling, deleting, search, and status filters.
- Projects and project membership are being added in PR #7.
- Each user has a personal project; legacy tasks without a project are migrated there.
- Project owners can invite existing users; invitees can accept invitations.
- Shared project members can work with project tasks; non-members are isolated.

## Important test lessons
- Keep tests isolated with a fresh temporary database.
- When changing the database layer, test isolation must be re-checked.
- Render checks must only expect deployments for `main`; feature branches are tested by CI but are not production deployments.
- Git branch divergence can block a merge even when CI is green; rebuild feature branches from current `main` when needed.

## Experiment rule
Increase complexity step by step. Record real failures, fixes, and manual intervention required. The goal is to find the practical quality/complexity ceiling rather than assume it.
