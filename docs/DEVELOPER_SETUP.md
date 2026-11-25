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
python -m app.cli suppress add owner@shop.ph       # do-not-contact; also queues a scrub of stored contacts
python -m app.cli suppress add shop.ph --domain    # a whole domain (subdomains need their own entry)
python -m app.cli suppress check owner@shop.ph     # list | remove work the same way
python -m app.cli backfill-prospects               # build the outbound pipeline from history (once after upgrading)
python -m app.cli rescore-prospects                # refresh outbound priority scores (nightly; engagement decays)
```

### Live discovery and enrichment

Discovery runs on the worker (`discover_businesses`, `run_campaign` and `enrich_business` jobs), so start
`python -m app.cli worker` before using **Admin → Discovery**.

* **OpenStreetMap** is free and needs no key, so it's the source to test code against. Use the public Overpass
  server fairly: keep the pause between campaign queries (`DISCOVERY_QUERY_DELAY_SECONDS`) and a
  `DISCOVERY_USER_AGENT` that identifies us. If it times out, point `OVERPASS_ENDPOINT` at a mirror
  (e.g. `https://overpass.kumi.systems/api/interpreter`).
* **Google Places** needs `GOOGLE_MAPS_API_KEY` from a project with billing enabled.
* **Fixture** returns fictional listings (555 numbers, `.example` sites) for offline work and demos. It is
  off in production unless `DISCOVERY_ALLOW_FIXTURE=true`.
* **Enrichment** scrapes the business's own website for free. RDAP (`ENRICH_ALLOW_RDAP`) and Hunter
  (`HUNTER_API_KEY` **and** `ENRICH_ALLOW_HUNTER`) are opt-in. Hunter only runs for leads scoring at least
  `ENRICH_PAID_MIN_SCORE`. Paid calls are counted in the `provider_usage` table. Social pages (Facebook etc.)
  are never scraped.
* Tests never touch the network: `tests/conftest.py` turns off enrichment's website fetches, and the discovery
  tests replace `http_client_factory`.

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
* **Google discovery fails with `429 RESOURCE_EXHAUSTED`:** the key's daily quota is used up (trial-tier keys
  allow about 100 text searches a day). It isn't a code bug, and the quota resets about 24 hours later. Use
  OpenStreetMap in the meantime.
* **OpenStreetMap finds 0 businesses for a PH city:** OSM often names the city without "City" ("Angeles", not
  "Angeles City"). The provider already tries "X", "X City" and "City of X". If that still finds nothing, look
  the place up on openstreetmap.org and use its exact name.
* **Overpass `504`/timeouts:** the public server is busy. Retry later or set `OVERPASS_ENDPOINT` to a mirror.
* **A password set through `su -c "..."` doesn't work:** inside double quotes, bash expands `$` and `!` (`$!` is
  the last background job's PID) before Postgres sees the password. Pick passwords with no shell-special
  characters for anything set this way.
* **Self-hosting in a Proxmox unprivileged LXC:**
  * The stock Debian `redis-server.service` fails with `status=226/NAMESPACE`. Use a minimal systemd unit
    without the sandboxing options. Redis logs go to `/var/log/redis/redis-server.log`, not journald.
  * Minimal Debian containers have no `sudo`: use `su postgres -c "psql -c \"...\""`.
  * The Proxmox web console mangles multi-line pastes. Run `bind 'set enable-bracketed-paste off'` in that
    shell first.
* **Windows PowerShell 5.1 reports `NativeCommandError` for git/gh:** it wraps their progress output on stderr.
  Read the actual output. Avoid `2>&1` on native commands.
