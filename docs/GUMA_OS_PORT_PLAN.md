# Guma OS → GumaWeb Port Plan

> **Status:** proposed, 2026-11-25. **Source:** `samgamoza/guma-os` @ `dde193a` (branch `feat/live-full-cycle`).
> **Target:** this repo (GumaWeb).
> **Brand decision:** *Guma OS* is the company/platform name; *GumaWeb* is the product. This is a
> **feature** port, not an architecture port — the code stays `gumaweb`.

## 1. Goal and rules

Bring guma_os's lead-sourcing strengths — real discovery, contact enrichment, per-fact provenance,
domain-level suppression and SSRF-hardened fetching — into GumaWeb, whose pipeline is already
end-to-end (score → generate → publish → outreach → claim → upgrade) but whose discovery is
CSV/JSON import only.

1. **Port features, not the kernel.** GumaWeb already has its own job queue, event outbox, audit
   log, repositories, auth and AI ledger. None of guma_os's kernel packages come over (see §6).
2. **Python, in-process.** No TypeScript sidecar. Everything ported has a Python equivalent
   (`httpx`, `dnspython` — both already in `requirements/base.txt` — and optional `playwright`).
3. **Fit existing homes.** Discovery → `domains/business_discovery`; outreach compliance →
   `services/outreach_service.py`; background work → `services/job_queue.py` + `workers/factory_worker.py`.
4. **guma_os tests are the spec.** Each ported module carries over its test cases (fetch-mocked,
   no network, no spend). Counts are listed per step.
5. **Compliance before reach.** Suppression and provenance land *before* any new contact source can
   write emails (same sequencing guma_os locked in its handoff §0f).

## 2. What GumaWeb already has (reuse, don't duplicate)

| Need | Already in GumaWeb | Gap |
|---|---|---|
| Discovery port | `domains/business_discovery/sources.py` — `BusinessSource` protocol, `RawBusinessRecord`, CSV/JSON | No live providers |
| Source enum | `DiscoverySource` incl. `CHAMBER`, `GOOGLE_BUSINESS` | No `OSM` |
| Normalize/dedupe | `normalization.py` (`build_dedupe_key`, `normalize_phone`, `is_free_email`, …) | — |
| Scoring | `scoring.py` (website/domain missing, contactability, industry value) | Ignores rating/reviews; optional add |
| Run tracking | `DiscoveryRun` model | No saved/re-runnable campaigns |
| Suppression | `OutreachSuppression(email, reason)`, checked in outreach | Email-only; no domain kind; no retroactive scrub |
| SSRF guard | `domains/integrations/webhooks.py` `validate_webhook_url` (DNS-resolved private-IP check) | No redirect re-validation, no byte cap, no fetch wrapper |
| Background jobs | `JobQueue` (`SKIP LOCKED`, dedupe keys) + `JobKind` | No discover/enrich/scrub kinds |
| Cost ledger | `AIGeneration` (tokens, latency) | No money column; nothing for paid data APIs |
| Audit | `AuditLog`, `domains/audit` | Not per-fact |
| Admin UI | `frontend/src/app/admin/{businesses,outreach,…}` | No discovery/campaign/suppression pages |

## 3. Step 0 — prep (half a day)

- Branch `feat/guma-os-port` off `main`. (GumaWeb `main` currently has uncommitted
  `docker-compose.yml` / Proxmox docs work — commit or stash that first; don't mix it in.)
- **Rename the Phase 4 `guma_os` module** now that "Guma OS" is the company — **done**:
  `{api/v1/endpoints,models,schemas}/guma_os.py` → `automation.py` (not `integrations.py`, which
  would collide with the existing `domains/integrations` and `services/integration_service.py`),
  `services/os_events.py` → `business_events.py`, `test_phase4_guma_os.py` → `test_phase4_automation.py`,
  plus docstrings/doc headings. Pure rename, no table changes (table names don't include `guma_os`);
  the historical migration filename `0004_guma_os_…` is left as is.
- Add `docs/requirements/` cross-reference: this file supersedes "Phase 1 ships file-based
  importers" in `sources.py`'s docstring once Step 3 lands.

## 4. Port steps

Ordered by dependency. Each step is one PR, green on `scripts/test.sh`, with an Alembic migration
where noted.

### Step 1 — `safe_fetch` (foundation for every outbound crawl) — **done**

> Landed as `app/core/net.py` + `tests/unit/test_safe_fetch.py` (all 16 original scenarios + 30 more).
> Tightened beyond the original: connections are **pinned to the validated address** (Host header and
> TLS SNI keep the real hostname), closing the DNS-rebinding gap between check and connect; CGNAT
> (100.64/10), IPv4-mapped IPv6 and credentials-in-URL are refused. `webhooks.py` now uses the same
> classifier.

- **From:** `adapter-maps/src/safe-fetch.ts` (178 lines, **16 tests**).
- **To:** `app/core/net.py` — `safe_fetch(url, *, timeout, max_bytes, max_redirects, user_agent) -> SafeFetchResult`
  and `UnsafeUrlError`, on `httpx` with `follow_redirects=False`.
- Behaviour to preserve: http(s)-only; resolve host via DNS and reject loopback/private/link-local/
  reserved/metadata (`169.254.169.254`) *by resolved address*; re-validate **every** redirect hop;
  stream the body with a hard byte cap (no unbounded `.text`).
- **Refactor** `validate_webhook_url` to share the same IP classifier (`_is_private`/`_never_allowed`)
  so there is one SSRF policy in the codebase.

### Step 2 — suppression v2 + contact provenance (compliance first) — **done**

> Landed as migration `0006`, `domains/outreach/suppression.py`, `services/suppression_service.py`,
> `domains/business_discovery/contacts.py`, `services/contact_service.py`, the `/outreach/suppressions`
> API and `cli suppress`. Deviations from the sketch below: the old `email` column is **dropped** in the
> same migration (backfilled into `value`, case-variant duplicates merged) rather than kept for a release,
> because a NOT NULL unique `email` cannot hold domain rows; and the API lives under `/outreach/suppressions`
> next to the rest of outreach. Unsubscribing always records the address itself, so lifting a domain
> suppression never re-subscribes someone who opted out personally. Verified on SQLite and PostgreSQL,
> including an upgrade → downgrade → upgrade round trip on seeded rows.

**2a. Domain-level suppression.** From `persistence/src/ports.ts` `SuppressionRepository` +
`adapter-postgres/src/postgres-suppression-repository.ts` + `decision/src/policy.ts` `DNCPolicy`
(**policy 4 tests, persistence conformance**).
- Migration: `outreach_suppressions` gains `kind` (`email`|`domain`) and `value`; backfill
  `kind='email', value=email`; unique `(kind, value)`; drop the old unique on `email` (keep the column
  one release for safety, then drop).
- `OutreachRepository.is_suppressed(email)` → true if the exact email **or its domain** is suppressed.
- Admin API: `GET/POST/DELETE /api/v1/admin/suppressions` (RBAC admin) + CLI `python -m app.cli suppress add|remove|list`
  (port of `admin/src/suppress.ts`). Every add/remove → `AuditLog`.

**2b. Contact points with provenance.** From the additive provenance fields in
`profile/src/profile.ts` (`source_ref`, `acquired_at`, `value_type`, `verification_status`, `purpose`,
`retention_until`, `policy_decision`, `reason_code`).
- New table `business_contacts`: `business_id`, `kind` (email|phone|owner), `value`, `source`,
  `source_ref`, `value_type` (observed|derived|predicted|user_supplied), `verification_status`
  (unverified|verified|invalid), `confidence`, `purpose`, `policy_decision` (allow|redacted|blocked),
  `reason_code`, `acquired_at`, `retention_until`, `discovery_run_id`. Unique `(business_id, kind, value)`.
- **Promotion rule** (pure function in `domains/business_discovery/contacts.py`): `Business.email`/`phone`
  is set only from a contact that is `observed` or `user_supplied`, not `blocked`, not suppressed.
  Predicted/guessed emails (RDAP, pattern) are stored but **never promoted** and never used by outreach.
- Outreach keeps reading `Business.email`, so no outreach code changes beyond 2a.

### Step 3 — live discovery providers

- **From:** `adapter-maps/src/osm.ts` (139), `discovery.ts` (295: Google Places + fixture + `scoreLead`),
  `adapter-pcci/src/pcci-discovery.ts` (189). **Tests: discovery 26, pcci 4.**
- **To:** `domains/business_discovery/providers/` — `osm.py`, `google_places.py`, `fixture.py`
  (`pcci.py` lands in Step 7). Each implements a new `DiscoveryProvider` protocol:
  `id`, `name`, `discover(query: DiscoveryQuery) -> list[RawBusinessRecord]`.
  Map provider output straight to the existing `RawBusinessRecord` (place id → `source_ref`), so
  normalization, dedupe and `BusinessService` import are reused unchanged.
- Enum: add `DiscoverySource.OSM`; Google → `GOOGLE_BUSINESS`; PCCI → `CHAMBER`.
- Keep `CITY_BBOX` and `categoryToOverpassSelectors`. Keep the Overpass inter-query delay (free
  community service — do not remove).
- Config (`core/config.py`): `DISCOVERY_DEFAULT_SOURCE`, `GOOGLE_MAPS_API_KEY`. Google needs a
  billing-enabled key (per-SKU free caps; demo keys cap at 100 text searches/day → 429).
- Optional scoring add: rating + review count as a small "operating business" signal in
  `scoring.py` (from `scoreLead`). Keep GumaWeb's weights authoritative; add with tests.
- New `JobKind.DISCOVER` handled by the factory worker, so discovery never blocks an HTTP request.

### Step 4 — contact enrichment waterfall

- **From:** `adapter-maps/src/enrichment.ts` (456), `domain-signals.ts` (77), `mx-lookup.ts` (38),
  `rdap.ts` (96), `hunter.ts` (82). **Tests: enrichment 55, domain-signals 12, mx 4, rdap 7, hunter 7.**
- **To:**
  - `domains/enrichment/extract.py` — pure: `extract_contacts(html)`, `extract_json_ld_contacts(html)`,
    plausibility filters (generic local parts, tracker/CDN domains), `domain_of`, `detect_tech_stack`.
  - `services/enrichment_service.py` — tiers behind an `EnrichmentProvider` protocol:
    `website_scrape` (free, always; via `safe_fetch`), `rdap` (free, opt-in `ENRICH_ALLOW_RDAP`,
    yields only *predicted* contacts), `mx` (verification signal), `hunter` (paid, opt-in
    `ENRICH_ALLOW_HUNTER` + `HUNTER_API_KEY`, only for score ≥ threshold).
  - `enrich_businesses(...)` with bounded concurrency, and **both** suppression checks from the
    original: domain check *before* any tier runs (prevents paid spend on suppressed businesses),
    email check *after* (nothing suppressed is ever written).
- Output writes `business_contacts` rows with provenance (Step 2b), then applies the promotion rule.
- New `JobKind.ENRICH_BUSINESS`, enqueued per business after discovery, dedupe key `enrich:<id>`.
- **Paid-API cost:** new table `provider_usage` (`provider`, `operation`, `units`, `cost_micros`,
  `business_id`, `created_at`); Hunter lookups write here. (`AIGeneration` stays the LLM ledger;
  it has no money column and local models are free.) Fixes guma_os handoff §12 item 8.

### Step 5 — crawl campaigns + admin UI

- **From:** `admin/src/crawl-runner.ts` (341, **16 tests**), `crawl-campaigns.ts` (273, **20 tests**),
  `read-model.ts` skipped-row visibility (**10 tests**).
- **To:**
  - Model `discovery_campaigns` (`name`, `cities[]`, `categories[]`, `sources[]`,
    `enrichment_sources[]`, `target`, `per_query`, `created_by`); `DiscoveryRun` gains `campaign_id`
    and per-source progress in a JSON column.
  - `services/discovery_service.py`: cities × categories × sources sweep, merge + dedupe, stop at
    `target`, cancel. Single-flight per campaign via job dedupe key `campaign:<id>`.
  - API: `/api/v1/admin/discovery/{campaigns,runs,sources}` — `sources` returns the categorized
    descriptor list (directory / registry / contact-finder / social-mining) for the picker.
  - Frontend: `admin/discovery` (campaign list, run, live progress), `admin/suppressions`, and a
    provenance panel on the business detail page. Rebuild in Next.js; the guma_os server-rendered
    dashboard does not come over.
  - Keep the guma_os lesson: rows that can't be shown are **counted and surfaced**, never silently
    dropped from headline numbers.

### Step 6 — retroactive suppression scrub

- **From:** `admin/src/suppression-scrub.ts` (96, **4 tests**).
- **To:** `JobKind.SCRUB_SUPPRESSION`, enqueued on every suppression add: mark matching
  `business_contacts` `policy_decision='blocked', reason_code='SUPPRESSED_*'`, clear a matching
  promoted `Business.email`, and set any queued `OutreachMessage` for it to `SKIPPED`. Malformed rows
  are skipped and counted, not fatal. Audit-logged with counts.

### Step 7 — headless browser + PCCI (optional extra)

- **From:** `adapter-browser/src/playwright-page-runner.ts` (67, 3 tests), `adapter-pcci` (189, 4 tests).
- **To:** `app/core/browser.py` (`PageRunner` protocol, Playwright impl) behind an optional
  `requirements/browser.txt` and env flag `DISCOVERY_ALLOW_PCCI`. Not in the default worker image
  (Chromium is ~150 MB) — separate `worker-browser` image/profile in docker-compose.
- **Fix the known flake while porting:** guma_os's PCCI tests hit the live site and time out ~1 run
  in 3. Ported tests use **recorded HTML fixtures**; one opt-in live smoke test only.
- Follow-up: website-scrape tier falls back to `PageRunner` when a plain fetch returns an
  empty/JS-only page (guma_os §12 item 11).

### Step 8 — retire guma_os

- Port `AGENT_HANDOFF.md` §10 "Gotchas & lessons" into `docs/DEVELOPER_SETUP.md` (Redis in
  unprivileged LXC, Google quota, `$!` in passwords, Overpass etiquette).
- Archive `samgamoza/guma-os` on GitHub (read-only). Do not delete.

## 5. Order, size, tests

| Step | Lines ported (TS src) | Tests carried | Migration | Depends on |
|---|---|---|---|---|
| 0 Prep / rename | — | existing | no | — |
| 1 safe_fetch | ~180 | 16 | no | — |
| 2 Suppression v2 + contacts | ~250 | ~10 + new | **yes** | — |
| 3 Discovery providers | ~430 | 26 | enum | 1 |
| 4 Enrichment | ~750 | 85 | **yes** (`provider_usage`) | 1, 2 |
| 5 Campaigns + admin UI | ~600 + UI | 46 | **yes** | 3, 4 |
| 6 Retroactive scrub | ~100 | 4 | no | 2 |
| 7 Browser + PCCI | ~260 | 7 (fixtures) | no | 3 |
| 8 Retire | — | — | no | all |

Roughly **2.5k lines of real logic and ~190 tests**. Steps 1, 2 and 6 can go in parallel with 3.

## 6. Deliberately NOT ported

| guma_os package | Why not |
|---|---|
| `bus`, `adapter-redis-bus` | GumaWeb has the `domain_events` outbox + Redis Streams relay |
| `persistence`, `adapter-postgres` (except suppression semantics) | SQLAlchemy models + Alembic |
| `profile` (schema, projection, state machine) | `Business` + `BusinessProfile`; only provenance fields come over (Step 2b) |
| `decision`, `aico` | GumaWeb's `generate_candidate` + plan entitlements cover it; only `DNCPolicy` semantics come over |
| `flags`, `auth`, `capability`, `contracts`, `core`, `worker`, `harness`, `testing` | Kernel scaffolding with GumaWeb equivalents (config, RBAC, job queue, pytest) |
| `greeting-capability`, `website-capability` | Demo / duplicated by GumaWeb's website factory |
| `admin` dashboard HTML | Rebuilt in the Next.js admin (Step 5) |
| `adapter-anthropic` | See open decision 1 |

## 7. Open decisions (founder)

1. **Claude as an optional content backend?** guma_os used Claude Haiku (~$0.007/site); GumaWeb is
   local-first (Qwen/DeepSeek). Porting it would be an extra `agents/` backend and would need a
   `cost_micros` column on `AIGeneration`. Recommendation: defer; local-first is a stated principle.
2. **Google Places billing key** — needed for Google as a real source; OSM works free meanwhile.
3. **Hunter.io key** — Tier 3 is built but was never validated with a real key.
4. **PCCI terms** — confirm scraping the chamber directory is acceptable (the sources docstring
   already requires respecting ToS/robots and preferring official exports).
5. **Malformed guma_os data** — CT105 Postgres holds ~3k crawled profiles, duplicate demo rows and
   one malformed row (`b9a65e1b-…`). Import real crawled businesses into GumaWeb (one-off script via
   `RawBusinessRecord`) or start fresh?

## 8. Definition of done

- `scripts/test.sh` green, including a PostgreSQL run (`TEST_DATABASE_URL`) for the migrations.
- An admin can create a campaign ("dental clinic" × "Cebu City", sources OSM + Google), run it, watch
  progress, see businesses appear with enriched contacts and their provenance, suppress a domain, and
  see existing contacts at that domain blocked and queued outreach skipped.
- No predicted/guessed contact is ever sent outreach (asserted by a test).
- Every paid lookup has a `provider_usage` row.
