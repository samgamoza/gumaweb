# Developer Setup

## Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Docker + Compose | 24+ | Easiest path: runs everything |
| Python | 3.12+ | Images pin 3.12. The test suite also passes on 3.14. |
| Node.js | 22+ | Portal; `corepack enable` provides pnpm |
| pnpm | 9+ | Package manager for `frontend/` |

## Option A: the whole stack in Docker

```bash
cp .env.example .env
docker compose up --build
```

The `migrate` service applies migrations, seeds plans, templates, the admin user and 10 fictional
demo businesses, then runs one **factory batch** that generates and publishes their sites. The `worker`
service processes queued jobs (`POST /websites/generate-batch`, admin **Factory jobs** page).

**Port clashes?** Every host port is configurable in `.env` (`GW_PORTAL_PORT`, `GW_API_PORT`, `GW_SITES_PORT`,
`GW_POSTGRES_PORT`, `GW_REDIS_PORT`, `GW_MAILPIT_PORT`, `GW_SMTP_PORT`); the public URLs follow automatically.

### Local AI (Phase 2)

```bash
docker compose --profile ai up -d ollama ollama-pull   # Ollama + qwen2.5:1.5b (CPU-friendly, ~1 GB)
# set AI_ENABLED=true in .env, then:
docker compose up -d api worker
```

Override the models with `COMPOSE_LLM_PRIMARY_MODEL` / `COMPOSE_LLM_SECONDARY_MODEL` (e.g. `qwen2.5:7b`). Small
models get many sections rejected by the quality gates and fall back to template copy, which is expected. Inspect the
reasons in a website's `quality_report.content_notes`, and usage on the admin overview (**AI factory**).

| URL | What |
|---|---|
| http://localhost:3000 | Portal (landing, `/login`, `/admin`, `/portal`, `/claim/<subdomain>`) |
| http://localhost:8000/docs | API (Swagger UI) |
| http://localhost:8080/abc-construction/ | A generated site served by nginx |
| http://localhost:8025 | Mailpit, which catches claim verification and outreach emails |

Sign in as `admin@gumaweb.io` / `ChangeMe!2026` (from `.env`). Change it.

**Try the claim flow:** open a site → *Claim this website* → submit with any email → open the
verification email in Mailpit → set a password → you land in the customer portal → edit the hero text →
reload the site, which has been republished without the claim banner.

## Option B: run the code natively (data services in Docker)

```bash
docker compose up -d postgres redis mailpit
scripts/dev-setup.sh                 # creates backend/.venv and installs frontend deps
cp .env.example backend/.env         # DATABASE_URL points at localhost:5432
scripts/migrate.sh --demo

# API with dev preview of published sites at /sites/<subdomain>/
cd backend && SITE_URL_TEMPLATE='http://localhost:8000/sites/{subdomain}/' uvicorn app.main:app --reload
# Portal
cd frontend && pnpm dev
# Generate + publish the demo sites
cd backend && python -m app.cli generate --publish
```

No Docker at all? Use SQLite: `DATABASE_URL=sqlite:///./dev.db`, then `alembic upgrade head`. The schema is
portable. Use PostgreSQL for anything beyond a quick look.

## Tests and quality gates

```bash
scripts/test.sh          # ruff + pytest + migration drift check + tsc + next build
```

or piece by piece:

```bash
cd backend
.venv/bin/python -m pytest -q          # unit tests plus API flows on in-memory SQLite (~15 s)
.venv/bin/python -m ruff check app tests
```

* `tests/unit/`: pure domain rules (scoring, normalization, classification, blueprint, content, quality,
  SEO, risk, sequences, storage, and rendering **every** template manifest).
* `tests/api/`: HTTP-level flows through FastAPI with in-memory email and SMS senders: generate →
  publish → claim (email / SMS / manual review) → portal edits → plan change, plus outreach,
  analytics and RBAC.
* `tests/e2e/smoke_test.py` (repo root): run against a live deployment after each deploy.
* **PostgreSQL run:** `TEST_DATABASE_URL=postgresql+psycopg://gumaweb:gumaweb@localhost:5432/gumaweb_test pytest`
  runs the same suite on the production dialect (use a disposable database). `scripts/test.sh` runs both when set.

## Project conventions

* **Where code goes:** business rule → `app/domains/<context>/` (no I/O). Use case → `app/services/`.
  HTTP → `app/api/v1/endpoints/`. Never put rules in endpoints.
* Services commit. Endpoints don't. Every state change worth auditing calls `audit()`. Every major
  operation calls `record_event()`.
* Raise `app.core.exceptions` errors (`NotFoundError`, `ConflictError`, ...). They map to HTTP automatically.
* Settings come only from `app.core.config.Settings` (environment variables).
* Python: ruff (line length 120), type hints everywhere. TypeScript: strict mode.

## Common tasks

### Add a template

1. Create `templates/manifests/<slug>.yaml` (copy an existing one): `slug, name, category, industries,
   theme.palette, pages[].sections[] {component, variant}`.
2. Reuse existing components or add `templates/components/<type>/<variant>.html.j2`. Components receive
   `block` (the section content), `business`, `root`, `link(target)`, `api_url` and `subdomain`. Read values
   with `block.get('field')` because the environment uses `StrictUndefined`.
3. Run `pytest tests/unit/test_factory_domain.py`. Every manifest is rendered and quality-checked automatically.
4. Run `POST /api/v1/templates/sync` (or the *Sync from repository* button on the admin Templates page).

### Add an industry

Add an `IndustrySpec` to `app/domains/business_profile/industry_catalog.py` (keywords, services, audience,
tone, commercial value, schema.org type, FAQ). Map it to a template category.

### Add a database change

See [DATABASE_DESIGN.md → Migration workflow](DATABASE_DESIGN.md#migration-workflow).

### Useful CLI

```bash
python -m app.cli seed [--demo]           # idempotent reference data
python -m app.cli sync-templates
python -m app.cli create-admin EMAIL PASSWORD
python -m app.cli generate --limit 100 --publish   # synchronous (small runs)
python -m app.cli enqueue --limit 1000             # queue a factory batch
python -m app.cli worker [--once]                  # jobs, event relay, automation tick, stale-call cleanup
python -m app.cli dispatch-outreach
python -m app.cli rescore-leads                    # refresh lead scores silently (nightly / after upgrading)
python -m app.cli mail-bootstrap --hostname H --domain D  # first-run setup of a fresh Stalwart
```

Phase 4 local testing: set `WEBHOOK_ALLOW_PRIVATE=true` to send webhooks to a receiver on your machine
(`http://host.docker.internal:<port>/...` from Docker; metadata/link-local addresses stay blocked). Set
`VOICE_GATEWAY_TOKEN` to exercise `/api/v1/voice/*`, or use the simulator under **Portal → Receptionist**.

### Phase 5: custom domains and business email locally

**Custom domains.** The dev sites server routes by Host header, so you can try a domain without DNS:
`curl -H 'Host: yourdomain.ph' http://localhost:${GW_SITES_PORT}/`. For HTTPS, start Caddy with its own CA:
```bash
CADDY_TLS_MODE=internal GW_CADDY_HTTPS_PORT=8443 docker compose --profile domains up -d caddy
curl -k --resolve yourdomain.ph:8443:127.0.0.1 https://yourdomain.ph:8443/
```
Verification needs a real TXT record. Locally, mark a domain verified in the database to try the rest of the
flow (the verification logic itself is covered by tests).

**Business email** (self-hosted Stalwart):
```bash
STALWART_RECOVERY_ADMIN=admin:<pick-a-password> docker compose --profile mail up -d stalwart
STALWART_RECOVERY_ADMIN=admin:<same> docker compose exec api python -m app.cli mail-bootstrap \
    --hostname mail.gumaweb.test --domain gumaweb.test        # prints the admin account once
# then set MAIL_PROVIDER=stalwart, STALWART_USERNAME, STALWART_SECRET; unset STALWART_RECOVERY_ADMIN
docker compose --profile mail up -d --force-recreate stalwart && docker compose up -d --force-recreate api worker
```

## Troubleshooting

* **`pnpm` scripts say `node` is not recognized (Windows):** run the binaries directly, e.g.
  `node node_modules/next/dist/bin/next dev`.
* **Port 8000 already in use:** run the API on another port and set `NEXT_PUBLIC_API_URL`,
  `API_PUBLIC_URL` and `SITE_URL_TEMPLATE` to match.
* **Published sites missing their claim-banner link:** `FRONTEND_URL` was wrong at publish time.
  Fix it and republish (`POST /websites/{id}/publish`).
