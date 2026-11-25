# API Reference

Base URL: `https://api.gumaweb.io/api/v1` (local: `http://localhost:8000/api/v1`).
Interactive docs: **`/docs`** (Swagger UI, with an *Authorize* button for the OAuth2 password flow).
OpenAPI JSON: `/api/v1/openapi.json`.

## Conventions

* **Auth:** `Authorization: Bearer <access_token>`. Access tokens last 30 minutes. Exchange the refresh
  token at `POST /auth/refresh`. Tokens carry `sub` (user id), `role`, `type` and `jti`.
* **Roles:** `admin`, `operator`, `readonly` (staff) and `customer`. *Reader* below means
  admin/operator/readonly. *Staff* means admin/operator.
* **Pagination:** `?page=1&page_size=25` (max 200) → `{items, total, page, page_size}`.
* **Errors:** `{"error": "<code>", "detail": "<message or field errors>"}` with HTTP 400/401/403/404/409/422/429/502.
  Codes your client should handle include `duplicate_business`, `already_claimed`, `password_required`,
  `already_customer`, `no_customer`, `rate_limited` and `publish_failed`.
* **Rate limits:** login 20 per 15 minutes per IP. Claims 5 per hour per IP and per email. Claim verification 30 per hour.
  Contact form 10 per hour per IP. Analytics beacon 300 per hour per IP per site.

## Authentication

| Method | Path | Access | Description |
|---|---|---|---|
| POST | `/auth/login` | public | JSON `{email, password}` → `TokenPair` |
| POST | `/auth/token` | public | OAuth2 password form (Swagger UI) |
| POST | `/auth/refresh` | public | `{refresh_token}` → new `TokenPair` |
| GET | `/auth/me` | any user | Current user |
| POST | `/auth/change-password` | any user | `{current_password, new_password}` |

## Businesses (discovery and intelligence)

| Method | Path | Access | Description |
|---|---|---|---|
| GET | `/businesses` | reader | Filters: `q, status, industry, city, min_score, generate_candidate`. Sorted by score. |
| POST | `/businesses` | staff | Create → normalized, deduplicated (409 `duplicate_business`), scored |
| POST | `/businesses/import` | staff | Multipart `file` (`.csv` or `.json`, ≤ 10 MB) → `DiscoveryRun` with per-row errors |
| GET | `/businesses/discovery-runs` | reader | Recent import runs |
| GET / PATCH | `/businesses/{id}` | reader / staff | Read / update (re-normalizes and re-scores) |
| DELETE | `/businesses/{id}` | staff | Archive (soft delete) |
| POST | `/businesses/{id}/score` | staff | Recompute the opportunity score |
| POST | `/businesses/{id}/profile?force=` | staff | Build the intelligence profile (manual profiles are kept) |
| GET / PATCH | `/businesses/{id}/profile` | reader / staff | Read / edit services, audience, tone, tagline |

CSV columns: `name` (or `business_name`), `industry, city, province, address, phone, email, website,
facebook, google_business_url, description, source_ref` (or `business_id`). Sample:
[`database/seeds/sample_businesses.csv`](../database/seeds/sample_businesses.csv).

## Templates

| Method | Path | Access | Description |
|---|---|---|---|
| GET | `/templates?category=` | reader | Master templates |
| POST | `/templates` | admin | Create (validated like a manifest) |
| POST | `/templates/sync` | staff | Upsert `/templates/manifests/*.yaml` and the component registry |
| GET | `/templates/components` | reader | Component library (type × variant) |
| GET / PATCH | `/templates/{id}` | reader / admin | Read / update; `is_default` is unique per category |

## Websites (factory and publishing)

| Method | Path | Access | Description |
|---|---|---|---|
| GET | `/websites?status_filter=` | reader | Websites with business name and template |
| POST | `/websites/generate-batch` | staff | **Phase 2.** `{business_ids?, limit, publish, priority}` → 202 `{enqueued, skipped}`; factory workers build the sites (deduplicated per business while queued) |
| POST | `/websites/generate` | staff | `{business_id, template_slug?, publish?}` → profile, template, blueprint, content, SEO, QA (409 if one exists) |
| GET | `/websites/{id}` | reader | Includes `quality_score` and `quality_report.issues` |
| GET | `/websites/{id}/blueprint` | reader | Blueprint JSON |
| GET / PUT | `/websites/{id}/content` | reader / staff | Content blocks; PUT `{section_key, updates, republish}` |
| GET | `/websites/{id}/seo` | reader | SEO metadata, schema.org markup, per-page `pages` meta and the latest `audit` (score, checks, content gaps) |
| POST | `/websites/{id}/regenerate` | staff | `{template_slug?, reset_content?, publish?}`; keeps edited content unless reset; live sites are republished |
| POST | `/websites/{id}/publish` | staff | `{force?}` (force is admin-only) → `Deployment` |
| POST | `/websites/{id}/unpublish` | staff | Remove the live site, keep releases |
| GET | `/websites/{id}/deployments` | reader | Deployment history |

## Claims

| Method | Path | Access | Description |
|---|---|---|---|
| POST | `/claims` | public | `{subdomain, claimant_name, claimant_email, claimant_phone?, method: email\|sms\|business_identity, evidence?, ref?}` |
| POST | `/claims/verify` | public | `{token}` (email link) or `{claim_id, otp}` (SMS), plus `password` for new accounts. Returns `tokens` when approved immediately. |
| GET | `/claims?status_filter=` | reader | Review queue |
| GET | `/claims/{id}` | reader | Includes `risk_score` and `risk_factors` |
| POST | `/claims/{id}/approve` | staff | Approve a verified claim in `manual_review` |
| POST | `/claims/{id}/reject` | staff | `{notes}` |

Status flow: `pending_verification → (approved | manual_review → approved | rejected) | expired`.

## Customer portal

| Method | Path | Access | Description |
|---|---|---|---|
| GET | `/customer/dashboard` | customer | Business, website, plan, 30-day stats, recent leads |
| GET / PUT | `/customer/content` | customer | Edit allow-listed fields (`hero, about, services, faq, cta, contact, testimonials`); republishes |
| PUT | `/customer/profile` | customer | Name, description, phone, email, address, Facebook; syncs the contact section and republishes |
| GET | `/customer/leads` | customer | Contact-form submissions |
| GET / POST | `/customer/subscription` | customer | Current plan / `{plan}` to change (emits `customer_upgraded`) |
| GET / POST | `/customer/media` | customer | List / upload images (multipart `file`, optional `alt_text`; JPEG/PNG/WebP ≤ 5 MB; SVG refused) |
| GET | `/customer/media/{id}/file` | customer | Image bytes for portal previews |
| DELETE | `/customer/media/{id}` | customer | Delete; removes it from the gallery/hero and republishes |

The dashboard includes `seo: {score, content_gaps[{key, message, impact, section}]}`. Content updates accept
`gallery.images: [{asset_id, alt}]` and `hero.image: {asset_id, alt} | null` (null means use the generated artwork). Only the
shared library or the business's own uploads can be referenced.

## Phase 3: CRM, booking, chatbot (customer portal, plan-gated)

Gated endpoints return `403 {"error": "plan_upgrade_required"}` when the plan lacks the module.

| Method | Path | Plan | Description |
|---|---|---|---|
| GET | `/customer/features` | any | `{plan, features: {crm, booking, ai_chatbot, ...}}` |
| GET / POST | `/customer/crm/contacts` | Business+ | List (`q, stage, source`, paging) / create (409 `duplicate_contact`) |
| GET / PATCH / DELETE | `/customer/crm/contacts/{id}` | Business+ | Detail with activity timeline / update (stage changes are logged) / delete |
| POST | `/customer/crm/contacts/{id}/activities` | Business+ | Log a note, call, email or meeting |
| GET | `/customer/crm/pipeline` | Business+ | Count and deal value per stage |
| GET | `/customer/crm/export.csv` | Business+ | CSV export |
| GET / PUT | `/customer/booking/settings` | Business+ | Hours, services, slot step, notice, auto-confirm; enabling adds the widget to the site |
| GET | `/customer/booking/appointments?start=&end=&status_filter=` | Business+ | Appointments |
| POST | `/customer/booking/appointments/{id}/{confirm\|cancel\|complete\|no_show}` | Business+ | Owner actions (notify the visitor) |
| GET / PUT | `/customer/chatbot/settings` | AI | Greeting, hand-off message, lead collection; enabling adds the chat widget |
| GET / POST | `/customer/chatbot/knowledge` | AI | Knowledge entries (website-derived plus custom) |
| PUT / DELETE | `/customer/chatbot/knowledge/{id}` | AI | Edit (becomes custom) / delete |
| POST | `/customer/chatbot/knowledge/rebuild` | AI | Re-import from website content |
| GET | `/customer/chatbot/conversations[/{id}]` | AI | Conversation list / transcript |

Public endpoints (used by the site widgets, rate limited):

| Method | Path | Description |
|---|---|---|
| GET | `/public/sites/{subdomain}/booking` | Bookable services, timezone, window (404 if off or not entitled) |
| GET | `/public/sites/{subdomain}/booking/slots?date=&service=` | `[{start, label}]` |
| POST | `/public/sites/{subdomain}/booking` | `{service, start (with offset), name, email?/phone?, notes?}` → 201, or 409 `slot_taken` |
| GET | `/public/booking/{token}` · POST `/public/booking/{token}/cancel` | Manage-link details / cancel |
| POST | `/public/sites/{subdomain}/chat` | `{message ≤ 1000, session_token?}` → `{session_token, reply}` |

## Phase 4: Automations, receptionist, integrations

| Method | Path | Plan | Description |
|---|---|---|---|
| GET / POST | `/customer/automations` | Business+ | List / create a rule `{name, trigger, config, conditions, actions[≤5]}` (422 on invalid template or fields) |
| GET | `/customer/automations/presets` | Business+ | Recommended rules |
| POST | `/customer/automations/presets/{key}` | Business+ | Install a preset |
| PATCH / DELETE | `/customer/automations/{id}` | Business+ | Enable/disable or edit / delete |
| GET | `/customer/automations/runs` | Business+ | Run log with per-action results |
| GET / PUT | `/customer/voice/settings` | Voice AI | `{enabled, phone_number, forward_number, take_messages}` (409 if the number is taken) |
| POST | `/customer/voice/test-call` · `/customer/voice/test-call/{id}/turn` | Voice AI | Portal simulator → `{call_id, say, action, transfer_to}` |
| GET | `/customer/voice/calls` | Voice AI | Call log: transcript, outcome, summary |
| GET / POST | `/customer/integrations/api-keys` | Business+ (login only) | List / create `{name, read_only}` → `key` shown once |
| DELETE | `/customer/integrations/api-keys/{id}` | Business+ (login only) | Revoke |
| GET / POST | `/customer/integrations/webhooks` | Business+ (login only) | List / create `{url, events[]}` (422 for private or unsafe URLs) |
| PATCH / DELETE | `/customer/integrations/webhooks/{id}` | Business+ (login only) | Update or re-enable / delete |
| GET | `/customer/integrations/webhooks/{id}/secret` · POST `…/rotate-secret` | Business+ (login only) | Signing secret |
| POST | `/customer/integrations/webhooks/{id}/test` | Business+ (login only) | Queue a signed `ping` |
| GET | `/customer/integrations/deliveries` | Business+ (login only) | Delivery log |

CRM contacts now include `lead_score`, `lead_temperature` and `score_reasons`.

**API keys:** send `Authorization: Bearer gw_live_…` to any `/customer/*` endpoint. Read-only keys get `403` on writes,
and "login only" endpoints reject keys with `403`.

**Telephony gateway** (server-to-server, header `X-Voice-Gateway-Token`; `503 voice_gateway_disabled` if unset):

| Method | Path | Description |
|---|---|---|
| POST | `/voice/inbound` | `{to, from}` → 201 `{call_id, say, action}` (404 if no enabled receptionist owns `to`) |
| POST | `/voice/calls/{id}/turn` | `{text}` (ASR output) → `{say, action: continue\|hangup\|transfer, transfer_to}` (409 after the call ended) |
| POST | `/voice/calls/{id}/end` | Caller hung up → call record with outcome and summary (idempotent) |

**Verifying a webhook** (receiver side):
```python
import hashlib, hmac, time
def verify(secret: str, body: bytes, header: str) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    if abs(time.time() - int(parts["t"])) > 300:
        return False
    expected = hmac.new(secret.encode(), f"{parts['t']}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])
```

## Phase 5: Digital presence, domains and email (customer portal)

| Method | Path | Plan | Description |
|---|---|---|---|
| GET | `/customer/presence` | any (parts by plan) | Kit: brand, assets (with `locked`), bios, hashtags; posts, `google`, `seo`, `checklist` on Professional+ |
| POST | `/customer/presence/regenerate` | any | Rebuild from the current website |
| GET | `/customer/presence/assets/{name}.png` | basic: `logo`, `profile`, `facebook-cover`; others Professional+ | Image, rendered on first request then cached |
| GET | `/customer/presence/download.zip` | Professional+ | Images, bios, posts, Google listing text, SEO profile |
| PUT | `/customer/presence/checklist` | Professional+ | `{step, done}` (Google Business Profile steps) |
| GET / POST | `/customer/domains` | Professional+ to add | List / connect `{domain}` → DNS records to add (409 if another account holds it) |
| POST | `/customer/domains/{id}/verify` | | Check the `_gumaweb.<domain>` TXT record now (503 `dns_unavailable` on resolver failure) |
| PUT | `/customer/domains/{id}/website` | Professional+ | `{serve_website}`: switches the site's canonical URL and republishes |
| DELETE | `/customer/domains/{id}` | | Stops serving, deletes its email on the mail server |
| POST | `/customer/domains/{id}/email` | Professional+ | Enable email on a verified domain → mail DNS records |
| POST | `/customer/domains/{id}/email/check` | | Compare required mail records with DNS (`status`: dns_pending / active / suspended) |
| POST | `/customer/domains/{id}/mailboxes` | Professional+ | `{local_part, display_name?, kind: mailbox\|forward, forward_to[]}` → a mailbox's `password` is returned once |
| POST | `/customer/domains/{id}/mailboxes/{mid}/reset-password` | | New password (returned once) |
| DELETE | `/customer/domains/{id}/mailboxes/{mid}` | | Delete on the mail server too |

Public: `GET /public/domains/tls-check?domain=…` → 200 only for verified domains serving a site (Caddy `ask`).
Email endpoints answer `503 business_email_unavailable` when no mail server is configured.

## Outreach

| Method | Path | Access | Description |
|---|---|---|---|
| GET / POST | `/outreach/campaigns` | reader / staff | List / create `{name, sequence?, target_filter{industry, city, min_score, limit}, launch?}` |
| POST | `/outreach/campaign` | staff | **Send Campaign**: create, enroll eligible businesses and schedule Day 0/3/7/14 in one call |
| GET | `/outreach/campaigns/{id}` | reader | Campaign |
| POST | `/outreach/campaigns/{id}/launch` | staff | Enroll new eligible businesses (idempotent) |
| POST | `/outreach/campaigns/{id}/dispatch` | staff | Send due messages now (the CronJob does this every 15 minutes) |
| GET | `/outreach/campaigns/{id}/stats` | reader | sent, opens, clicks, claims, conversions, unsubscribes |

Eligible means: published, unclaimed, has an email, not suppressed, and not already enrolled. Hidden
tracking routes: `GET /public/outreach/open/{token}.gif`, `/public/outreach/click/{token}` (302 to the
site) and `/public/outreach/unsubscribe/{token}`.

**Do-not-contact list.** A suppression is one email address or a whole domain (`acme.ph` blocks every address at
exactly that domain, not its subdomains). Enrollment, dispatch and contact enrichment all check both. Any staff
member may add one; only an admin may remove one. Every add/remove is audit-logged.

| Method | Path | Role | Description |
|---|---|---|---|
| GET | `/outreach/suppressions?kind=` | reader | List, newest first |
| POST | `/outreach/suppressions` | staff | `{kind: email\|domain, value, reason: unsubscribed\|requested\|bounced\|complaint\|legal, note?}`. Idempotent: `201` when created, `200` with the existing entry |
| DELETE | `/outreach/suppressions/{kind}/{value}` | admin | Remove; `404` if absent |
| GET | `/outreach/suppressions/check?email=` | reader | `{suppressed, matched_kind, matched_value}` |

CLI: `python -m app.cli suppress add|remove|check|list [VALUE] [--domain] [--reason R] [--note TEXT]`.

## Billing, analytics, administration

| Method | Path | Access | Description |
|---|---|---|---|
| GET | `/billing/plans` | public | Plan catalog (free, professional, business, ai, voice_ai) |
| GET | `/analytics/overview` | reader | KPIs (generated, published, claimed, paid, MRR, ARPB, claim rate) and the funnel |
| GET | `/analytics/websites/{id}?days=30` | reader | Daily page views, event totals, leads |
| GET | `/analytics/timeseries?days=30` | reader | Daily discovered, generated, published, claims started/completed, page views, leads |
| GET | `/analytics/templates` | reader | Sites, published, claimed, claim rate, average quality per template |
| GET | `/analytics/industries` | reader | Businesses, candidates, sites, claimed, average score per industry |
| GET | `/analytics/ai` | reader | AI calls, tokens, latency and acceptance per task/model; AI-written section share; image library reuse |
| GET / POST | `/admin/users` | admin | List / create staff users |
| PATCH | `/admin/users/{id}` | admin | Role, active flag, name (you cannot demote or deactivate yourself) |
| GET | `/admin/audit-logs` | reader | Filters: `action, entity_type, entity_id` |
| GET | `/admin/events` | reader | Domain event outbox |
| GET | `/admin/jobs?status_filter=&limit=` | reader | Factory job queue (kind, status, attempts, worker, result/error) |
| GET | `/admin/jobs/stats` | reader | Counts by status |
| POST | `/admin/jobs/{id}/retry` | staff | Re-queue a failed job |

## Public (generated sites)

| Method | Path | Description |
|---|---|---|
| GET | `/public/sites/{subdomain}` | Claim-page data with masked email and phone |
| POST | `/public/sites/{subdomain}/events` | Analytics beacon; body is JSON sent as `text/plain` (`page_view, claim_banner_click, contact_submit, phone_click`) |
| POST | `/public/sites/{subdomain}/contact` | Form-encoded lead; JSON reply with `Accept: application/json`, otherwise a 303 redirect back to the site |
| GET | `/health/live`, `/health/ready` | Probes (`/healthz` and `/metrics` also exist at the root) |

## Example: discover → claim

```bash
API=http://localhost:8000/api/v1
TOKEN=$(curl -s $API/auth/login -H 'Content-Type: application/json' \
  -d '{"email":"admin@gumaweb.io","password":"ChangeMe!2026"}' | jq -r .access_token)
BID=$(curl -s $API/businesses -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Santos Plumbing","city":"Angeles City","phone":"0917 555 0102"}' | jq -r .id)
curl -s $API/websites/generate -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d "{\"business_id\":\"$BID\",\"publish\":true}" | jq '{subdomain,url,quality_score}'
curl -s $API/claims -H 'Content-Type: application/json' \
  -d '{"subdomain":"santos-plumbing","claimant_name":"Jose","claimant_email":"jose@example.com"}'
# verification email → Mailpit (http://localhost:8025) → link opens /claim/verify?token=...
```
