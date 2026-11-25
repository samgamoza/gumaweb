# System Architecture

> Status: **Phases 1 (MVP), 2 (Factory Scale) and 3 (Platform Expansion) implemented**. The requirements live in [`docs/requirements/`](requirements/)
> (documents 01–20). This file describes how the code implements them and why.

## 1. Shape of the system

GumaWeb is a **modular monolith**: one FastAPI deployable whose code is split along bounded contexts
with one-directional dependencies. Each context can be extracted into its own service (doc 18's
`api / builder / outreach / ...` charts) without rewriting domain logic.

```text
                         ┌──────────────────────── Kubernetes (guma-core) ─────────────────────────┐
 Business owner ──HTTPS──▶ ingress-nginx ─┬─ app.gumaweb.io ───▶ portal (Next.js 15)               │
                         │                ├─ api.gumaweb.io ───▶ api (FastAPI, gunicorn/uvicorn)   │
 Site visitor ───HTTPS──▶│                └─ *.gumaweb.io ─────▶ sites (nginx, static files)       │
                         │                                         ▲                              │
                         │  api ──▶ PostgreSQL (+pgvector)          │ RWX volume or MinIO bucket   │
                         │      ──▶ Redis (rate limits, events)     │                              │
                         │      ──▶ SMTP (self-hosted MTA)  api/workers write published sites ────┘
                         │  worker ×N (HPA): factory_jobs → pipeline → publish; outbox → Redis     │
                         │  CronJobs: enqueue factory batch (nightly), outreach dispatch (15 min)  │
                         └──────────────────────────────────────────────────────────────────────────┘
                            guma-ai: vLLM (Qwen / DeepSeek, OpenAI-compatible); FLUX/SDXL images (optional)
```

**Static first** (doc 03): generated websites are plain HTML/CSS files with about 1 KB of inline JS
(an analytics beacon and the contact form). They need no application server and cost almost nothing to host.

## 2. Layering (backend)

```text
api/            HTTP: routing, auth/RBAC, request/response schemas. No business rules.
  ↓
services/       Application services = use cases. Own the transaction (commit), audit + events.
workflows/      Multi-step pipelines (website assembly) composed from services + domain logic.
workers/        Factory worker: drains the job queue, relays the event outbox (Phase 2).
agents/         AI layer: LLM content agent, image generators, LLM client; rules fallbacks.
  ↓
domains/        Pure business rules: no DB, no HTTP. Scoring, classification, blueprint,
                content, quality gate, SEO, risk, sequences, plans, KPIs. Unit-tested in isolation.
repositories/   Query objects over SQLAlchemy models.
models/         SQLAlchemy ORM (system of record schema).
core/           Settings, security (JWT/bcrypt/tokens), rate limiting, exceptions, logging.
```

Dependencies only point downward. `domains/` imports nothing from `services/`, `api/` or `models/`
(the models import the domain enums). This keeps the rules portable for a future service split.

## 3. Bounded contexts → code

| Context (requirement doc) | Domain rules | Service / workflow | Tables |
|---|---|---|---|
| **BusinessDiscovery** (04) | `domains/business_discovery/` normalization, dedupe key, opportunity scoring, source connectors, lifecycle | `BusinessService` | `businesses`, `discovery_runs` |
| **BusinessProfile** (05) | `domains/business_profile/` industry catalog, classifier, profiler | `ProfileService`, `agents/business_agents.py` | `business_profiles` |
| **TemplateManagement** (06) | `domains/template_management/` manifest parsing, component discovery, template resolver | `TemplateService` | `templates`, `template_components` |
| **WebsiteFactory** (07, 09) | `domains/website_factory/` blueprint, content generator, quality gate | `WebsiteGenerationWorkflow`, `WebsiteService` | `websites`, `website_content`, `media_assets` |
| **SEO** (07, 10) | `domains/seo/` titles, descriptions, local keywords, schema.org, robots, sitemap | (in workflow) | `seo_metadata` |
| **Publishing** (10) | `domains/publishing/` renderer, storage backends, subdomain policy | `PublishingService` | `deployments` |
| **Claims** (11) | `domains/claims/` risk scoring, review policy | `ClaimService` | `claims` |
| **Customers** (12) | `domains/customers/` roles, editable-content policy | `CustomerService` | `users`, `customers`, `leads` |
| **Outreach** (13) | `domains/outreach/` Day 0/3/7/14 sequence, sandboxed templates | `OutreachService` | `outreach_*` (4 tables) |
| **Billing** (14) | `domains/billing/` plan catalog, entitlements, payment-provider seam | `BillingService` | `plans`, `subscriptions` |
| **Analytics** (13, 14) | `domains/analytics/` KPI math | `AnalyticsService` | `site_events` |
| **Audit** (19) | `domains/audit/` audited actions | `services/support.audit()` | `audit_logs`, `domain_events` |

## 4. The factory pipeline

Implements doc 09 (*Business Profile → Template Selection → Component Selection → Content Injection →
Image Assignment → SEO → Quality Validation → Build*) in `workflows/website_generation.py`:

1. **Discover**: create/import → normalize (phone to E.164 digits, URLs, emails) → dedupe on
   canonical *name + city + phone* → **score** (website missing 35, domain missing 10, social 15,
   phone 10, email 10, industry value ≤ 20). A business with no owned website, reachable contact
   info and a score ≥ 60 becomes a `generate_candidate`.
2. **Profile**: the industry catalog classifies the business (explicit hint > keyword match; generic
   words such as "clinic" count half) and supplies services, audience, tone and keywords.
3. **Template selection**: industry-specific template > category default > newest in category > `general`.
4. **Blueprint**: renderer-agnostic JSON (pages → sections → component/variant/content key, theme,
   navigation, business facts). Stored on `websites.blueprint`.
5. **Content**: `ContentGenerator` fills one row per section in `website_content` (the content cache).
   Rows edited by a customer/operator are **preserved** on regeneration unless `reset_content=true`.
6. **SEO**: title ≤ 60 chars, description 50–160, local keywords, schema.org `LocalBusiness` subtype.
7. **Quality gate**: pages exist, components exist, required fields present, SEO lengths, contact
   available → score 0–100. Publishing requires ≥ 70 (admins can force).
8. **Publish**: Jinja2 renders static files → `SiteStorage` writes an immutable release
   `_releases/<sub>/v<n>/` then atomically swaps the live `<sub>/` directory (local) or prefix (S3).
   Keeps 3 releases for rollback. Wildcard DNS + wildcard TLS mean no per-site DNS call.

The nightly `factory-batch` CronJob runs steps 2–8 for the top N candidates
(`python -m app.cli generate --limit 1000 --publish`, sized to the "1000+ sites/day" goal).

## 5. Claim-first conversion

```text
published site ──claim banner──▶ /claim/<sub> ──▶ POST /claims ──(risk score)──▶ email link | SMS OTP
      ▲                                                                         │
      └── republished without banner ◀── ownership transfer ◀── auto (risk < 60) ┴─ manual review (staff)
```

* **Abuse protection** (doc 11): per-IP and per-email rate limits (Redis), honeypot fields, hashed
  single-use tokens and OTPs (SHA-256, never stored in plaintext), OTP attempt cap, expiry, and a
  risk score. Matching the email or phone on record lowers risk. Disposable domains, competing claims,
  IP bursts and document-based claims raise it. One approved claim per business is enforced by a
  **partial unique index**.
* **Ownership transfer** creates the `Customer` and a free `Subscription`, rejects competing claims,
  stops scheduled outreach, attributes the conversion to the outreach message that drove it, and
  republishes the site without the banner.

## 6. Events and audit

Every major operation appends to `domain_events` **in the same transaction** as the state change
(transactional outbox): `business_discovered`, `business_scored`, `website_generated`,
`website_published`, `claim_started`, `claim_completed`, `customer_upgraded`, `outreach_sent`, and more.
When contexts split into services, a relay worker publishes unprocessed rows to Redis Streams or NATS
and stamps `processed_at`. No dual-write problem, no lost events.

Security-relevant actions (logins, failed logins, claims, content updates, subscription changes, user
management) go to `audit_logs` with actor, role and IP.

## 7. AI seams

| Seam | Implementation | Next |
|---|---|---|
| `ContentGenerator` protocol | `TemplateContentGenerator` (always); `LLMContentGenerator` when `AI_ENABLED` (§10.2) | per-industry prompt tuning from acceptance data |
| `Agent` protocol (`agents/base.py`) | `BusinessProfilerAgent` (rules) | LLM classifier only when rules confidence is low |
| `LLMClient` | `OpenAICompatibleClient` → Ollama (dev) / vLLM (prod): retries, JSON mode, token usage | |
| `ImageGenerator` | `ProceduralImageGenerator` (SVG, zero cost), `HttpImageGenerator` (FLUX/SDXL) | |
| PostgreSQL | `pgvector` installed | BGE embeddings for semantic dedupe/search (Phase 3) |
| `SiteRenderer` | Jinja2 (milliseconds per site) | Astro build worker behind the same interface |

**Integrity rule:** generated copy never invents facts. It makes no claims about years in business,
awards or prices, and it never fabricates testimonials. The testimonial and gallery components
render nothing until real data exists. Every unclaimed site discloses that GumaWeb created it from
public information.

## 8. Key decisions

| # | Decision | Rationale |
|---|---|---|
| ADR-1 | Modular monolith, DDD contexts | One deployable while the team is small; hard boundaries make a later split mechanical. |
| ADR-2 | Synchronous SQLAlchemy 2.0 + psycopg 3 | Generation has no I/O-bound AI steps yet; sync code is simpler and FastAPI runs it in a threadpool. Async can be adopted per service later. |
| ADR-3 | Portable column types (UUID/JSONB/TIMESTAMPTZ on PG, generic elsewhere) | The full test suite runs on SQLite in seconds. Migrations are verified for drift with `alembic check`. |
| ADR-4 | Enums as `VARCHAR + CHECK` instead of native PG enums | Adding a value is a cheap migration with no `ALTER TYPE` locking. |
| ADR-5 | Templates as YAML manifests + Jinja components in git | Templates are reviewed like code and synced to the DB (`POST /templates/sync`). Industry decides layout without AI redesign (doc 06). |
| ADR-6 | Jinja2 renderer before Astro | No Node toolchain in the hot path. The output is identical static HTML. Astro stays behind `SiteRenderer`. |
| ADR-7 | Local disk ↔ S3 storage behind `SiteStorage` | The same layout works in dev (shared volume) and prod (MinIO/Ceph RGW + nginx proxy cache). |
| ADR-8 | Transactional outbox for events | Reliable event publication without a broker in Phase 1. |
| ADR-9 | JWT access (30 min) + refresh (14 days), RBAC roles admin/operator/customer/readonly | Doc 19. The `users` table already has OAuth (`oauth_provider/subject`) and MFA columns. |
| ADR-10 | Cookieless, IP-free analytics (daily-rotating salted hash) | Privacy compliance (doc 19) without a consent banner on every generated site. |
| ADR-11 | Job queue on PostgreSQL (`FOR UPDATE SKIP LOCKED`) instead of a broker | Transactional enqueue, horizontal workers, retries/backoff, stale-lock recovery, and no new infrastructure. Revisit beyond ~100 jobs/s. |
| ADR-12 | One prompt per section; per-section gates; template fallback | A bad answer costs one section, not the site. Small local models stay reliable. Sections cache independently. |
| ADR-13 | Readability gate is **relative**: `min(target, template baseline)` | A live run showed a fixed threshold rejecting AI copy that read better than our own template copy (About median Flesch 21). |
| ADR-14 | Generated images are decorative only; galleries show owner uploads only | Never present AI imagery as a business's work, staff or premises. |
| ADR-15 | Images are bundled into each site build (`assets/img/`) | Sites stay self-contained static artifacts; library changes never break a live site. |
| ADR-16 | Tests run on SQLite **and** PostgreSQL (`TEST_DATABASE_URL`) | The PostgreSQL run caught a GROUP BY bug that SQLite accepted. |
| ADR-17 | Capture contacts on every plan; gate only the CRM screens | Owners never lose leads; upgrading reveals history already collected (a natural upsell). |
| ADR-18 | Booking concurrency: per-business row lock + partial unique index on active start times | Serializes bookings per business without an exclusion constraint, which is not portable to SQLite. The unique index is the last line of defence. |
| ADR-19 | Chatbot = BM25 retrieval over a per-business knowledge base + grounded LLM phrasing | Fully local, no embedding service. It works as an FAQ bot when AI is off, and it hands off instead of guessing. |
| ADR-20 | Feature modules are injected at blueprint time (booking section, chat widget) | Plan or setting changes rebuild and republish the static site; widget JS ships only on pages that use it. |

## 9. Known limitations and the security roadmap

* Portal tokens live in `localStorage`. Next step: an httpOnly-cookie session via a Next.js route handler.
* One customer account manages one business (`customers.user_id` is unique). Multi-business owners come with organizations in Phase 3.
* MFA columns exist, but TOTP enrolment is not implemented yet. OAuth login (Google/Facebook) is not wired yet.
* Discovery connectors for DTI, Yellow Pages, Google Business and Facebook are interfaces only. They must use
  official exports or APIs and respect each source's terms of service.
* Redis caching of profiles is not implemented. AI content is cached in `ai_generations`.
* Keyword rankings (doc 12) need Search Console data. The SEO audit covers technical and content gaps only.
* SVG artwork is not used as an Open Graph image (social networks need raster). Raster images from the HTTP backend are.
* SMS uses a console sender. A local SMS gateway adapter is needed before enabling SMS claims in production.


## 10. Phase 2: Factory Scale

### 10.1 Job queue and workers
`POST /websites/generate-batch` (or the nightly `enqueue` CronJob) inserts `factory_jobs` rows, deduplicated per
business while queued or running. `python -m app.cli worker` runs anywhere (compose `worker`, K8s Deployment with HPA).
Each worker loops: claim one due job with `SELECT … FOR UPDATE SKIP LOCKED` → run its handler (`generate_website`,
`regenerate_website`, `publish_website`) → mark it succeeded, or failed with exponential backoff (30 s × 2^n, capped at
1 h, up to `max_attempts`). Jobs locked longer than 15 minutes are requeued (crashed worker). The same loop relays
unprocessed `domain_events` to the Redis stream `gumaweb:events`. Measured on the Docker stack: 7 template-only sites
in about 2 s (80–220 ms each).

### 10.2 AI content pipeline (`agents/content_agent.py`)
```text
template copy (fallback) ──┐
facts only ─▶ per-section prompt ─▶ Qwen ─▶ JSON extract ─▶ schema (pydantic, length limits)
  ─▶ business rules (known service names only; hero must mention the city)
  ─▶ quality gates (spam ≤ 10, fabricated claims, readability ≥ min(target, template baseline))
  ─▶ DeepSeek review (only for passing drafts; kept only if it passes the same gates)
  ─▶ accept → website_content.source = ai  |  reject → template copy + note in quality_report.content_notes
```
Every call is cached and metered in `ai_generations` (key = task, model, prompt version, input), so regenerating an
unchanged site costs zero tokens. The fabricated-claims detector rejects years in business, awards, licenses, prices,
ratings/reviews and statistics unless the fact is in the source data. Inference outages degrade to template copy and
never block generation.

**Live result** (qwen2.5:1.5b on CPU via Ollama, about 50 s/site): the model invented "Since 2015", left FAQ answers
empty and wrote spammy service copy. All of this was rejected by the gates, while vetted hero and CTA copy shipped.
Larger models (Qwen2.5-14B on vLLM, the production default) pass more sections. The gates never relax for small models.

### 10.3 Image factory
`AssetService.library_image()` keys library assets by `(industry, category, style, variant)`. The first site that needs
one generates it, and every later site reuses it (`usage_count`). `IMAGE_LIBRARY_VARIANTS` variants per key are spread
across businesses. Backends: procedural SVG in the template palette (default, zero cost) or a FLUX/SDXL server behind
`/images/generations`, falling back to procedural on failure. Customers upload JPEG/PNG/WebP (magic-byte sniffed; SVG
refused for XSS safety; per-business sha256 dedupe) and choose gallery and hero images. A business may only reference
library assets or its own uploads.

### 10.4 SEO engine
Unique title and description per page, schema.org `FAQPage` on FAQ pages, and an Open Graph image for raster heroes.
`domains/seo/audit.py` scores 14 checks and lists **content gaps** ranked by impact (address, services depth, photos,
testimonials, about story, …), only for sections the site's template can show. It is re-run after every content change
and shown in the customer portal.

### 10.5 Analytics
`/analytics/timeseries` (daily discovered, generated, published, claims, visits, leads), `/analytics/templates`
(sites, claim rate, quality per template), `/analytics/industries`, and `/analytics/ai` (calls, tokens, latency,
acceptance, AI-written share, image reuse).

### 10.6 Advanced templates
14 manifests (new: `contractor-modern-v1`, `dental-smile-v1`, `cafe-modern-v1`, `auto-repair-v1`) and a `hero/split`
variant with imagery. Businesses in the same industry spread deterministically across all industry-specific templates
(seeded by business id). Regeneration keeps a site's template unless an operator changes it.


## 11. Phase 3: Platform Expansion

Doc 20 Phase 3 deliverables (**CRM, AI chatbot, lead management, booking**), gated by plan per doc 14:
Business Plus unlocks CRM and booking; AI adds the chatbot and knowledge base.

### 11.1 CRM and lead management (`services/crm_service.py`)
Every inbound channel funnels into one **contact** per person per business, deduplicated by normalized email, then
phone (partial unique indexes). Each touch becomes an **activity**: form submission, booking, chat, stage change,
or a note/call/email/meeting logged by the owner. The pipeline runs new → contacted → qualified → won/lost, with an
optional deal value and per-stage totals. CSV export neutralizes spreadsheet formula injection. Capture runs on
**every** plan; only the CRM endpoints are gated (`403 plan_upgrade_required`).

### 11.2 Online booking (`domains/booking`, `services/booking_service.py`)
Weekly opening hours, slot step, service durations, buffer, minimum notice and booking window are evaluated in the
business's IANA timezone (default `Asia/Manila`). Bookings re-validate the exact slot under a per-business row lock,
and a partial unique index on active start times backstops races. Visitors get a confirmation email with a
manage/cancel link (`/booking/<token>`, token stored hashed). Owners get a new-booking email, and can confirm, cancel,
complete or mark no-shows in the portal. Every booking creates or updates a CRM contact.

### 11.3 AI chatbot (`domains/chatbot`, `agents/chat_agent.py`, `services/chatbot_service.py`)
```text
visitor message ─▶ clean/limit ─▶ lead capture (regex: email, PH mobile, "my name is …") ─▶ CRM
   ─▶ greeting? ─▶ BM25 over knowledge (website FAQ/services/about/contact + owner entries)
   ─▶ no hit → hand off (ask for details)          ─▶ AI off/down → best entry verbatim
   ─▶ local LLM with numbered knowledge only, visitor text fenced as data ─▶ {"unknown": true} → hand off
   ─▶ unsupported prices/years/ratings in the answer → discard, use the retrieval answer
```
Website-derived knowledge rebuilds when the owner edits content, while owner-written entries are kept. Conversations
are stored per session (hashed token), capped at 40 turns, and rate-limited per IP.
**Live check** (qwen2.5:1.5b via Ollama): grounded dental FAQ answers in about 2–19 s on CPU, an honest "please contact us"
when the knowledge didn't cover HMO acceptance, an off-topic question handed off, and a chat lead captured into the CRM.

### 11.4 Site integration
`site_features()` combines the plan's entitlements with the owner's switches. The blueprint then adds a `booking`
section to the contact page and a site-wide chat widget. Toggling a feature or changing plan rebuilds the blueprint,
creates content for any new section, and republishes. Downgrading removes the modules from the live site and the public
API. The widget JavaScript is vanilla, renders everything via `textContent`, and is emitted only on pages that use it.

## 12. Phase 4: Automation, Voice AI and Integrations

Doc 20 Phase 4 deliverables: **business automation, Voice AI, lead intelligence, Guma OS integration**. The plan
catalog is cumulative (Free ⊂ Professional ⊂ Business Plus ⊂ AI ⊂ Voice AI). Business Plus adds lead intelligence,
automation and integrations, and Voice AI adds the receptionist.

### 12.1 One event fan-out (`services/business_events.py`)
```text
CRM capture / stage change / hot lead ─┐
booking booked / cancelled ────────────┼─▶ emit(business, trigger, webhook event, context)   (same DB transaction)
call completed ────────────────────────┘     ├─ plan has automation + an enabled rule → job RUN_AUTOMATION
                                             └─ plan has integrations + subscribed endpoint → WebhookDelivery + job DELIVER_WEBHOOK
```
Side effects run in the worker through the durable job queue, so they get retries, backoff and crash recovery. A
failing receiver or SMTP server never fails the visitor's request.

### 12.2 Lead intelligence (`domains/crm/scoring.py`)
An explainable 0–100 score computed on every touch. It weighs source (booking > phone > chat/form > manual),
contactability, buying intent in English or Filipino ("how much", "magkano", "urgent", "today"), a booking made,
repeat inbound touches, recency (decays after 7 days, penalized after 30), and qualification or deal value. Bands:
hot ≥ 70, warm ≥ 40, cold, customer (won), closed (lost). Reasons are stored with the score and shown to the owner.
Crossing into *hot* fires `lead_became_hot`. The CRM list sorts by score. Because recency decays without new touches,
`gumaweb rescore-leads` refreshes every score without firing alerts. Run it nightly and once after upgrading, so
pre-Phase-4 contacts get scored.

### 12.3 Business automation (`domains/automation/rules.py`, `services/automation_service.py`)
Each rule has a trigger, conditions, and up to 5 actions.
- **Triggers:** `lead_captured`, `lead_became_hot`, `stage_changed`, `appointment_booked`, `appointment_cancelled`, `call_completed`, plus scheduled `appointment_reminder` (`hours_before`) and `contact_idle` (`idle_days`).
- **Conditions:** sources, stages, minimum score, services.
- **Actions:** email or SMS the customer, email the owner, set stage, add tag.

Templates use a sandboxed Jinja environment and are validated on save. Every run inserts an `automation_runs` row
keyed `rule:trigger:subject[:suffix]` (unique) inside a savepoint first. Replays, retries and overlapping ticks are
no-ops, so a customer never receives a duplicate message. Idle follow-ups key on the last-activity timestamp, which
means one follow-up per quiet period. `set_stage` writes directly and does not re-emit, so a rule cannot loop.
Scheduled triggers run from the worker maintenance loop every minute (`automation_tick`, safe on every replica).
Four presets are included: thank new leads, appointment reminder (24 h), hot lead alert, and idle follow-up (3 days).

### 12.4 Voice AI receptionist (`domains/voice/dialog.py`, `services/voice_service.py`)
```text
PSTN/SIP ─▶ telephony gateway (Asterisk ARI + local faster-whisper ASR + Piper TTS; not in this repo)
            POST /voice/inbound {to, from}  ─▶ greeting
            POST /voice/calls/{id}/turn {text} ─▶ {say, action: continue|hangup|transfer, transfer_to}
            POST /voice/calls/{id}/end          ─▶ outcome + summary
```
The dialog engine is a pure, deterministic state machine. Speech is "data in, words out" and the model only answers
free-form questions. Flows:
- **Intent:** classify the caller's request.
- **Booking:** service → day ("tomorrow", "bukas", "Friday", ISO) → offer 3 real slots → name → confirm → book. It uses the same booking rules, row lock and unique index as the website.
- **Questions:** answered from the chatbot knowledge base, with hand-off on low confidence.
- **Message taking:** creates a CRM contact (source phone) and emails the owner.
- **Transfer:** routes to the forward number.

Callers may ask for any open time, not just the three offered; if it's taken, the three nearest openings are offered.
After 2 misunderstood turns the receptionist falls back to taking a message, so callers never loop. Every call stores
its transcript, outcome and duration. A deterministic summary is written the moment the call ends. A
`summarize_call` job then replaces it with a model-written one if that passes the unsupported-claims check, so the
caller never waits on the model (inline, this had added ~19 s of silence before "Goodbye" on CPU). Calls whose
hang-up never arrives are closed as abandoned after an hour by worker maintenance. Completed calls emit `call_completed`. The gateway authenticates with
`X-Voice-Gateway-Token` (constant-time compare) and returns `503` when unconfigured. The portal simulator runs the
same engine (`is_test`, no outbound events).

### 12.5 Integration layer (`domains/integrations/webhooks.py`, `services/integration_service.py`)
- **API keys** (`gw_live_…`): only the SHA-256 hash is stored, and the key is shown once. A key acts as its owner on the customer API only; staff routes reject the customer role. Keys can be read-only, which blocks non-GET requests. They stop working when the plan loses integrations. Credential, key, webhook and billing changes require a real login session (`human_only`).
- **Webhooks:** events `lead.captured`, `lead.hot`, `contact.stage_changed`, `appointment.booked`, `appointment.cancelled`, `call.completed` (plus a test `ping`). The body is `{id, type, created, data}`. Headers are `GumaWeb-Event`, `GumaWeb-Delivery` and `GumaWeb-Signature: t=<unix>,v1=<hex HMAC-SHA256(secret, "t.body")>` (5-minute tolerance). Per-endpoint secrets are derived (`HMAC(server key, endpoint id : version)`), never stored, and rotate by bumping the version.
- **SSRF defence:** http(s) only, no userinfo, every resolved address must be public, HTTPS is required in production, the URL is re-validated at send time against DNS rebinding, and redirects are not followed.
- **Delivery:** up to 6 attempts with exponential backoff, and the endpoint auto-disables after 20 consecutive failures. Delivery logs are visible in the portal.

### 12.6 Grounding guard for model answers (chatbot and receptionist)
The live receptionist check exposed a gap. qwen2.5:1.5b answered "We accept most health maintenance organizations"
when the only relevant knowledge said "contact us to confirm the payment options". It also invented "ample parking".
Phase 3's check only catches invented prices, years and ratings. `ungrounded_terms()` now also rejects answers whose
content words are mostly absent from the retrieved knowledge, the question and the business name (≥ 4 novel terms
and > 50 % of content words). Such answers are replaced by the hand-off message. Faithful paraphrases pass.
**Known limit:** a lexical check cannot catch an improvised detail that reuses the caller's own words. For example,
"braces for adults" is answered "yes" when the knowledge only lists braces.

## 13. Phase 5: Digital Presence Factory

Doc 20 Phase 5: generate more than websites. The website, AI assistant and voice receptionist already exist
(Phases 1–4). Phase 5 adds the **presence kit** (social media kit, Google Business assets, SEO profile, logo),
**custom domains** and **business email**.

### 13.1 Presence kit (`domains/presence/*`, `services/presence_service.py`)
- **Built from facts only.** `PresenceFacts` holds what we know about the business (website content, profile,
  booking hours if the owner set them). Every bio, caption and description is assembled from those facts, so
  nothing invents offers, prices, years or awards. Opening hours are never assumed.
- **Social kit.** Bios fit each platform's visible limit (Facebook 101, Instagram 150, TikTok 80, X 160).
  Hashtags are local (`#Malolos`, `#MalolosDentist`). The starter posts are a first week: welcome, three service
  spotlights, an FAQ answer, how to reach you, and an online-booking invitation when booking is on. Links carry
  UTM tags so analytics show which channel brought the visit.
- **Google Business Profile pack.** GBP categories per industry. The description has no links, phone numbers or
  promotional wording (whole sentences that break the rules are dropped; deleting words leaves fragments), and
  doesn't repeat the about text. The pack warns when the name looks keyword-stuffed, a common suspension reason.
  Posts have no phone numbers. A checklist tracks claiming, verification and setup. We never edit the listing:
  that needs the owner's Google account.
- **SEO profile.** A canonical name/address/phone, inconsistencies between the business record, the site and
  the schema markup, keyword targets mapped to pages, and directory listings (Google, Facebook, Bing, Apple,
  Foursquare).
- **Images** (`render.py`, Pillow): logo (transparent), profile picture (monogram inside the circular crop),
  Facebook cover (text inside the mobile-crop safe zone), story (clear of the top/bottom UI), one card per post,
  and Google logo/cover. They use the site's template palette, with text colour chosen for WCAG contrast against
  the whole gradient. They are brand cards, never fake photos.
- **Cost model.** Every publish queues `generate_presence` (copy only, ~ms). Images render on first request and
  are cached per kit version, because pre-rendering ~10 images for each of up to 100k unclaimed sites would cost
  ~100 GB mostly for sites nobody claims. A new kit version drops the old images. Checklist progress survives.
- **Plans.** Every plan gets the logo, profile picture, cover and bios. Professional and up get posts, story,
  Google pack, SEO profile and the ZIP. Locked parts are withheld by the API, not just hidden.

### 13.2 Custom domains (`domains/presence/domains.py`, `services/domain_service.py`)
```text
owner adds bellavista.ph ─▶ TXT _gumaweb.bellavista.ph = gumaweb-verify=<token> ─▶ verify (dnspython)
   ─▶ "serve website" ─▶ website.url = https://bellavista.ph/ ─▶ republish (canonical, sitemap)
   ─▶ every publish also writes _d/bellavista.ph/ ─▶ nginx maps Host (bare or www.) to that directory
   ─▶ Caddy on-demand TLS asks GET /public/domains/tls-check?domain=… (200 only if verified and serving)
```
- Normalization accepts what owners paste (`https://www.X.PH/about`) and stores the bare punycode domain. It
  refuses IPs, internal and special-use names, and our own platform domain.
- **No squatting.** A domain belongs to one account. A never-verified claim is released after 7 days.
- **Revocation.** Verified domains are re-checked daily by an hourly `check_domains` job. If the TXT record
  disappears (the owner removed it, or the domain changed hands), the domain stops serving and the owner is
  emailed. Resolver errors are not treated as revocation.
- A downgrade stops serving. The storage layout (`_d/<domain>/`) works for local disk and S3. The nginx host
  regex only produces valid domain names, so the Host header cannot escape the directory.
- **Fixed during this phase:** the production nginx configs had an unquoted regex containing `{0,61}`, which
  nginx rejects. The production sites config had never passed `nginx -t`. It is quoted now, and all configs are
  validated in a container.

### 13.3 Business email (`domains/presence/mail.py`, `services/mail_service.py`, `services/mail_provider.py`)
- **Self-hosted Stalwart** (local-first; no paid mail API), managed through its JMAP management API. The adapter
  was built against a live Stalwart 1.1.1 rather than the docs, which have moved and disagree in places:
  - collections are index-keyed maps (`credentials: {"0": {"@type": "Password", "secret": …}}`);
  - forwarding outside the domain is a `MailingList` whose `recipients` is a set (`{"a@b.ph": true}`);
  - a domain is deleted only after its `DkimSignature` objects;
  - Stalwart generates and rotates DKIM keys itself, and `dnsZoneFile` lists every record it needs.
- **DNS records.** We show Stalwart's records rather than computing our own. MX, SPF, DKIM and DMARC are marked
  required. "Check DNS" refreshes the records (keys appear and rotate asynchronously) and compares them with
  real DNS.
- **Passwords** are generated (~96 bits), sent to the mail server and shown to the owner once. GumaWeb never
  stores them.
- **Limits.** Professional includes 5 mailboxes and Business Plus 20; forwards don't count. `postmaster@` and
  `abuse@` are reserved.
- **Downgrades suspend, never delete.** No new addresses can be created, but deleting someone's inbox because a
  plan changed would destroy their correspondence. Removing the domain deletes its addresses and the domain on the
  mail server.
- **No mail server configured** (`MAIL_PROVIDER=disabled`): email endpoints answer `503
  business_email_unavailable`, so the portal never pretends a mailbox exists.
- **First run.** `python -m app.cli mail-bootstrap` completes Stalwart's setup through `x:Bootstrap/set` (the
  same call its web wizard makes) and prints the permanent admin account once.
