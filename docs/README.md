# GumaWeb Documentation

> **We already built your website. Claim it.**

GumaWeb is an Autonomous Website Factory. It discovers businesses with little or no web presence,
generates professional static websites for them, publishes them on `<business>.gumaweb.io`, tells the
owners, and converts claimed sites into recurring SaaS customers.

## Documents

| Document | Read it when you need to... |
|---|---|
| [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) | understand the layers, bounded contexts, factory pipeline, claim flow, AI seams and decisions (ADRs) |
| [API_REFERENCE.md](API_REFERENCE.md) | call the API: all 106 `/api/v1` endpoints, auth, errors, rate limits |
| [DATABASE_DESIGN.md](DATABASE_DESIGN.md) | work with the 46 tables, constraints, indexes and migrations |
| [DEVELOPER_SETUP.md](DEVELOPER_SETUP.md) | run the project, run the tests, add templates or industries |
| [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) | deploy to Kubernetes with Helm, operate it, back it up |
| [requirements/](requirements/) | read the authoritative product and architecture requirements (01–20) |

## Phase 1 (MVP) scope and status

| Capability | Status | Where |
|---|---|---|
| Store businesses (manual + CSV/JSON import, normalize, dedupe) | ✅ | `domains/business_discovery`, `/businesses` |
| Score businesses (opportunity score, generate candidates) | ✅ | `domains/business_discovery/scoring.py` |
| Business intelligence profile (rules-based, AI-ready) | ✅ | `domains/business_profile`, `agents/` |
| Generate website blueprints (template + content + SEO + QA) | ✅ | `workflows/website_generation.py` |
| Manage templates (14 manifests, 14 components) | ✅ | `templates/`, `/templates` |
| Publish generated websites (static, versioned, local or S3) | ✅ | `domains/publishing`, `/websites/{id}/publish` |
| Manage claim requests (email / SMS / document, risk, review) | ✅ | `services/claim_service.py`, `/claims` |
| Customer login and portal (content, profile, leads, plan) | ✅ | `/customer`, `frontend/src/app/portal` |
| Admin dashboard (KPIs, businesses, websites, claims, outreach, templates) | ✅ | `frontend/src/app/admin` |
| Email outreach (Day 0/3/7/14, tracking, unsubscribe) | ✅ | `services/outreach_service.py` |

## Phase 2 (Factory Scale) status

| Capability | Status | Where |
|---|---|---|
| Durable job queue + horizontally scaled factory workers | ✅ | `services/job_queue.py`, `workers/`, `/websites/generate-batch` |
| AI content (Qwen + DeepSeek review) with quality gates, cache and fallback | ✅ | `agents/content_agent.py`, `domains/website_factory/content_quality.py` |
| Image factory: library reuse, procedural + FLUX/SDXL backends, customer uploads | ✅ | `services/asset_service.py`, `/customer/media` |
| SEO engine: per-page meta, FAQPage schema, audit with content gaps | ✅ | `domains/seo/`, portal **Search visibility** |
| Analytics: time series, templates, industries, AI usage | ✅ | `/analytics/*`, admin overview |
| Advanced templates (14) + variety-aware selection | ✅ | `templates/manifests/` |
| Event outbox relay to Redis Streams | ✅ | `workers/factory_worker.py` |

## Phase 3 (Platform Expansion) status

| Capability | Status | Where |
|---|---|---|
| Lead management + CRM (contacts, timeline, pipeline, CSV) | ✅ Business+ | `services/crm_service.py`, portal **Leads & CRM** |
| Online booking (hours, services, slots, confirmations, cancel links) | ✅ Business+ | `domains/booking`, portal **Bookings**, site widget |
| AI chatbot (knowledge base, grounded answers, hand-off, lead capture) | ✅ AI | `agents/chat_agent.py`, portal **AI assistant**, site widget |
| Plan entitlements + live site sync on plan/setting changes | ✅ | `domains/billing/entitlements.py`, `services/entitlements.py` |
