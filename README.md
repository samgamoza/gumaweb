# GumaWeb

**Autonomous Website Factory: "We already built your website. Claim it."**

GumaWeb finds local businesses without a website, generates a professional site for each one, publishes
it at `<business>.gumaweb.io`, invites the owner to claim it for free, and converts claimed sites into
recurring customers. It is local-first: self-hosted PostgreSQL, Redis, MinIO and SMTP, and local models
(Qwen / DeepSeek via Ollama or vLLM; FLUX/SDXL optional) behind strict quality gates.
**Status:** Phases 1 (MVP), 2 (Factory Scale), 3 (Platform Expansion: CRM, booking, AI chatbot) and 4 (Automation and integrations:
lead intelligence, business automation, AI voice receptionist, API keys and signed webhooks) and 5 (Digital
Presence Factory: presence kit, custom domains, business email on self-hosted Stalwart) are implemented.

```text
Directory record → Score → Profile → Template → Content + SEO → QA gate → Publish → Outreach → Claim → Upgrade
```

## Quick start

```bash
cp .env.example .env
docker compose up --build
```

* Portal: http://localhost:3000. Sign in with `admin@gumaweb.io` / `ChangeMe!2026`.
* API docs: http://localhost:8000/docs
* Generated sites: http://localhost:8080/abc-construction/ (9 demo sites are generated on first start)
* Captured emails: http://localhost:8025
* Ports clash with other projects? Set `GW_*_PORT` in `.env`.
* Local AI: `docker compose --profile ai up -d ollama ollama-pull`, then set `AI_ENABLED=true`.

## Repository

```text
backend/          FastAPI modular monolith (Python 3.12, SQLAlchemy 2, Alembic)
  app/api/          versioned HTTP API (/api/v1), auth + RBAC
  app/domains/      pure business rules, one package per bounded context (12)
  app/services/     use cases, transactions, audit, events
  app/workflows/    website assembly pipeline
  app/agents/       AI layer: LLM content agent, image generators (local models)
  app/workers/      factory worker: job queue + event outbox relay
  app/models/       SQLAlchemy models (33 tables)
  migrations/       Alembic
  tests/            unit + API tests
frontend/         Next.js 15 + TypeScript + Tailwind 4: landing, claim flow, customer portal, admin console
templates/        site manifests (YAML), Jinja2 components, shared CSS
generated-sites/  published site output in local storage mode
database/         rendered PostgreSQL DDL + sample seed CSV
infrastructure/   nginx (sites), postgres init
kubernetes/       namespaces, Helm chart, monitoring values, secret template
scripts/          setup, migrate, test, build, deploy, backup
tests/e2e/        post-deploy smoke test
docs/             architecture, API, database, setup, deployment, requirements/
```

## Development

```bash
scripts/dev-setup.sh     # venv + pnpm install
scripts/test.sh          # ruff, pytest, migration drift check, tsc, next build
```

Read [docs/README.md](docs/README.md) next.
