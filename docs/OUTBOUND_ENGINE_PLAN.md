# Outbound onboarding engine — development plan

Status: **in progress** (2026-11-26). C1, A1, A2 and A7a (private claim link + publish at claim) built; the rest
planned. Revised on 2026-11-26: AI agent layer
added, and **owner-triggered publishing** adopted (§1.1).
Replaces the earlier "sales CRM" plan, which centred on screens where people move prospects by hand. The founder's
direction: an **automated** engine, with people stepping in only where they lift conversion.

## 1. Goal

Turn crawler output into onboarded, paying clients with as little manual work as possible:

```text
discover ─▶ enrich ─▶ score ─▶ private draft ─▶ outreach with preview ─▶ owner clicks ─▶ confirm + verify ─▶ PUBLISH ─▶ upsell
 (crawlers)  (contacts) (BI)   + polish +        "Your website is ready,     (private        (short form,          (claimed =  (paid plans,
                               preview image      claim it"                  preview)        email/SMS code)        published)  verticals)
```

* **Conversion target:** passive claim conversion is typically 1–5% of published sites. The aggressive, multi-channel
  campaign (AI + human agents) aims for **6–15%** in the best case. That is a hypothesis: the engine measures the
  baseline first and reports what each channel, step and message adds (A6).
* **Upsell:** the same engine keeps working after the claim, pushing paid plans and the other verticals.
* **"Aggressive" means** many touches across channels with fast, behaviour-driven follow-up. It does not mean
  ignoring limits: opt-outs are honored on every channel, there are frequency caps and quiet hours, and every
  message carries an opt-out. Breaking these is a legal risk (Data Privacy Act, anti-spam rules) and also lowers
  conversion by burning sender reputation.

### 1.1 Owner-triggered publishing (adopted 2026-11-26)
Nothing is published for a business until its owner claims it.
* Qualified leads get a **private draft** (not live, not indexed). The time between building and sending is spent
  on polish (template choice, copy review, quality gate), so owners see a finished site, not a generic AI-feel one.
* The outreach email says **"Your website is ready, claim it"** with a preview image of *their* site. It's
  truthful ("ready", never "live"), with no public URL, only a private, unguessable, expiring claim link.
* The click opens the full private preview with a short form to confirm or correct details. The owner then verifies
  by email link or SMS code, and the site **publishes at claim**: claimed and live in one step.
* Why: it keeps the pull of "it already exists", there are no public pages without consent (privacy, complaints),
  sites are built well before anyone sees them, the owner supplies accurate data, and claiming is fast.
* Email notes: some apps block images, so there's a text headline, alt text and a working button without the image,
  plus a modest image size (spam filters). Photos from Google listings can't be reused (terms): drafts use category
  stock photos until the owner uploads their own.
* Sites published under the earlier flow keep the existing claim path.

## 2. What already exists

| Stage | Today | Gap |
|---|---|---|
| Discover + enrich | Discovery campaigns (OSM, Google, fixture), enrichment waterfall, contact provenance, suppression | — |
| Score | `score_business`: no website, no domain, social presence, phone/email, industry value → `score`, `generate_candidate` | Ignores contact *quality* (verified vs guessed), reviews/ratings, engagement |
| Generate + publish | Factory jobs; **started by hand** (`enqueue` CLI / admin batch) | Not automatic after discovery |
| Outbound | Email only, a fixed Day 0/3/7/14 sequence, enrolled by hand per campaign | No branching on behaviour, no SMS (console only), no calls, no claim-abandon recovery |
| Pipeline record | **C1 (built):** a prospect per draft-ready or published business, automatic stage + timeline | — |
| Upsell | Plans and verticals exist (Professional, Business, AI, Voice AI, custom domain, business email, presence kit) | No outreach to owners after the claim |
| Measurement | Per-campaign email totals | No funnel, no conversion rate, no attribution by channel/step/variant |

## 3. Steps

### C1 — pipeline record (built)
`prospects`, `prospect_activities`, `prospect_tasks`. Stages `new → contacted → engaged → conversation → claimed →
won`, plus `lost` and `do_not_contact`. Publishing, outreach (sent, first open, first click, unsubscribe), claims
(started, approved, rejected), billing (into/out of paid plans) and the suppression scrub record activities through
`ProspectService.record()`, which moves stages forward automatically:
* never backwards;
* conversions always apply, even from lost or do-not-contact;
* `requested`/`complaint`/`legal` suppressions close a prospect, `unsubscribed`/`bounced` block email only;
* customers keep their stage when suppressed.

`python -m app.cli backfill-prospects` rebuilds the pipeline from history (idempotent). The backfill is a CLI
command rather than part of the migration, so the migration stays independent of application code.

### A1 — lead compiler (automatic intake) — **built**

As built:
* `services/lead_compiler.consider()` runs at the end of each enrichment job, or right after discovery when no
  enrichment is queued. It queues a **private draft** (`publish: false`, `source: auto_compile`, priority 150, the
  same dedupe key as manual generation). It is off by default (`AUTO_COMPILE_ENABLED=false`). The cap counts auto
  jobs since midnight Philippine time.
* A draft that passes the quality gate enters the pipeline (`draft_ready` → stage `new`); one that fails stays out
  until improved. Nothing is published.
* `domains/sales/priority.py`:
  * fit = 0.4 × opportunity score;
  * email: confirmed 20, observed 16, listed 12;
  * phone: confirmed 10, observed or listed 8;
  * engagement: the strongest of claim started 30, click 20, open 10, at full value for 7 days, then ½, ¼, 0 after 30;
  * guessed contacts are never usable.
* Rescored on every activity and after enrichment; `rescore-prospects` runs nightly for decay. Stored as
  `score`, `score_reasons`, `channels`, `reachable` (migration 0012).
* `GET /pipeline/summary`, `GET /pipeline/prospects?ready=&stage=`, `GET /pipeline/prospects/{business_id}`.

Still to come with the onboarding funnel (A7): the polish pass and the preview images (headless-browser capture of
each draft, desktop + phone).

### A2 — campaign engine (the aggressive outbound) — **built**

As built:
* `playbooks` + `playbook_enrollments` (migration 0013). The default playbook, "Claim your website", is created on
  first use:
  * `intro` on enrollment;
  * `resend` 48h later if not opened or engaged;
  * `waiting` 24h after a click with no claim;
  * `almost` 2h after an abandoned claim;
  * a `call` task after 72h with no engagement, score ≥ 70.
* Step rules are pure (`domains/sales/playbooks.py`). Each step fires at most once, triggered by `enrolled`,
  `not_opened`, `clicked_not_claimed`, `claim_abandoned` or `no_engagement`, plus a delay.
* `OutboundEngine.tick()` runs as a `run_outbound` job about once a minute while `OUTBOUND_ENGINE_ENABLED` is on
  (single flight), or via `POST /pipeline/outbound/run` / `outbound-tick`. Each pass:
  * enrolls ready prospects, best score first, up to `OUTBOUND_DAILY_ENROLLMENT_LIMIT`;
  * stops an enrollment on conversion or closure, and completes it when every step is done or `max_days` passes.
* Guardrails:
  * quiet hours (20:00–08:00 Manila) and a weekly touch cap (3) defer a message, never skip it;
  * one message per prospect per pass;
  * suppression checked again at send time;
  * a prospect queued in a manual campaign isn't enrolled.
* Emails go out as outreach messages of the playbook's own campaign, so tracking, unsubscribe, the timeline and
  stage moves all work unchanged.
* SMS steps are skipped (`sms_unavailable`) until a gateway and phone opt-outs exist (E2 / A4).
* Drafts are enrolled too since A7a: their emails carry a private claim link instead of a public URL.
* API: `GET /pipeline/playbooks` (with per-step sent/skipped/failed), `PATCH /pipeline/playbooks/{id}` (admin),
  `GET /pipeline/tasks`.

Planned (original design):
* **Playbooks** replace the fixed sequence: steps with a channel (`email`, `sms`, `call_task`, later `ai_call`), a
  delay and a condition. Examples: *not opened in 2 days → resend with a new subject*; *clicked, no claim in 24h →
  "your site is ready to claim" follow-up + call task if score ≥ 70*; *claim started and abandoned → recovery
  message after 1h*; *no email → SMS, then call task*.
* **Engine tick** (worker, single flight): for each prospect in an active playbook, pick the next due step whose
  condition holds and send it through the channel. Each prospect's state is stored, every touch is recorded in the
  C1 timeline, and the engine is idempotent across restarts.
* **Guardrails:** opt-outs per channel and across all channels, at most N touches per prospect per week, quiet hours
  (Asia/Manila), stop on claim or conversation, suppression checked again at send time.
* **Channels:** email (live); SMS through a pluggable sender (a PH gateway is needed: decision E2); call tasks for
  humans (A4); AI calls later.

### A7 — onboarding funnel (owner-triggered publishing) + claim assistant

**A7a — built:** private claim link, draft preview, details form, publish at claim.
* `claim_links` (migration 0014): one per outreach email to a draft, valid `CLAIM_LINK_TTL_DAYS` (21); only the
  token's hash is stored. The engine now enrolls private drafts (`blueprint_ready`/`built`) as well as live sites.
* `/start/<token>` (frontend) shows the draft in a frame next to the form. API under `/public/start/{token}`:
  * `GET` opens it: the first open records the email's `link_clicked` (stats, timeline, playbook);
  * `GET …/site/{path}` serves the draft rendered on request (cached by content), never written to public
    storage; `noindex`, `no-referrer`, `no-store`, framable by the frontend origin only;
  * `PATCH …/details`: name, description, address, Facebook page and services update the draft at once (the new
    name replaces the old one throughout the copy; template copy that lists services is rewritten). The first
    answer records `claim_started`, so the playbook's abandoned-claim follow-up applies;
  * `POST …/claim` starts a normal claim (email link or SMS code).
* Phone and email answers show on the draft but wait on the link until ownership is proven, then apply at transfer:
  they are what verification relies on.
* A claim from a link that verifies with the email on record (or, by SMS, the phone on record) is approved and the
  site **publishes at claim**. Anyone else, such as someone the email was forwarded to, gets +40 risk and goes to
  manual review; approval then publishes. Drafts can't be claimed through the public `/claim/<subdomain>` page.

Still to come:
* **A7b:** polish pass before outreach, preview images (headless browser, desktop + phone) in the email, HTML email
  with a text fallback.
* **A7c:** claim assistant (below).
* Hours and logo/photo upload on the form.

Planned (original design):
* **Polish + preview:** polish pass on each draft before outreach; a headless browser in the worker captures a
  desktop and a phone preview image, served from an unguessable, non-indexed URL.
* **Private claim link** (`/start/<token>`, per prospect, expiring, renewed by later emails) opens the full draft
  preview. Opening it records `link_clicked`.
* **Short form**, prefilled from what we know: confirm or correct name, services, hours, area, contacts, optional
  logo/photo. Each answer is saved immediately and re-renders the draft; owner answers are stored as
  `user_supplied` contacts. Starting the form records `claim_started`.
* **Verify** by email link or SMS code (the existing claim checks), then **publish at claim**. A forwarded link
  can't publish someone else's business.
* **Claim assistant:** an AI chat beside the preview answers doubts ("Is it free? What's the catch? Can I change the
  photos?"). It reuses the site chatbot with a sales persona, facts only from the profile and plan catalogue, says
  it is an AI, and hands off to a person on request; it records with `source=ai`.
* Funnel measured in A6: draft ready → emailed → clicked → form started → claimed + published → paid.

### A3 — AI agent layer (was "AI personalization")
Agents run as playbook steps with a small set of tools: send a message on a channel, create a human task, send the
claim link, propose a plan. They never have free rein. Every action is an activity with `source=ai`, so A6 reports
AI's share of claims and upgrades separately from people's.
* **Research agent:** writes each prospect's brief and personal hook from profile, site, reviews and listing.
* **Copywriter agent:** per-business email/SMS and call scripts in English, Tagalog or Taglish, with A/B variants.
* **Conversation agent:** answers replies to email and SMS within minutes, handles objections, books callbacks,
  escalates.
* **Recovery agent:** abandoned claims and verification trouble.
* **Optimizer:** moves traffic between variants within set bounds (bandit); larger playbook changes need a person.

Guardrails: identifies as AI; uses only facts from the profile and catalogue; never invents prices or offers;
required opt-out; per-prospect touch caps (A2); hands complaints, legal questions and high-value deals to a person.
Models: the local LLM drafts in bulk; a stronger hosted model handles live conversations (decision E7). With AI
off, everything falls back to the plain templates.

### A4 — human in the loop (escalations)
People get only what the agents hand over or what scores high: hot leads (clicked or started a claim), escalated
replies, callbacks, high-value prospects. Tasks sit in a queue ordered by priority score. The queue offers a
one-screen call view: script (A3),
site link, claim link, contacts. Call outcomes are logged through `apply_call_outcome()` with the dialer seam's
outcome codes:
* interested → claim-link task/email;
* email captured → stored as a confirmed contact and becomes reachable by email;
* not interested → lost with a cooldown;
* do not call → blocks every channel;
* wrong number → contact marked invalid and flagged; the public number on their site isn't cleared.

Phone suppression is added here. When GumaDial is ready, its outcomes arrive through the same function
(`source=dialer`); see the parked `OUTREACH_DIALER_BRIDGE_PLAN.md`.

### A8 — payment gateway (prerequisite for closing upsells)
Billing today uses `ManualPaymentProvider`: a plan change involves no real payment. Add two gateways behind the
existing payment-provider interface (decision E6):
* **PayMongo** for PH clients (GCash, Maya, cards, billed in PHP);
* **Stripe** for international clients (cards, billed in their currency).

Each provides a checkout link, webhook-confirmed activation, renewals and failed-payment handling (`past_due`). The
gateway is chosen per customer by the business's country (`Business.country`, default PH), and an admin can
override it. Plan prices need a per-currency price list for international clients. Both adapters can be built and
tested in the providers' test modes before the live accounts are ready.

### A5 — upsell engine (account-manager agent)
After a claim, prospects move to upsell playbooks driven by usage signals: site traffic, leads received, bookings,
missed calls, unanswered chats. Examples: *leads arriving and no CRM → Business plan*; *traffic but no own domain →
custom domain*; *missed calls → Voice AI receptionist*. An account-manager agent picks the offer and timing. In the
owner portal it can complete the plan change once the owner confirms and pays (A8). The same engine, guardrails and
measurement apply; `won` and plan changes come from billing.

### A6 — cockpit and measurement
Admin → **Pipeline**:
* **Funnel:** discovered → published → contacted → engaged → claimed → paid, with conversion rates against the
  6–15% target, by week, city, industry and source.
* **Attribution:** which channel, playbook step and message variant preceded each claim and upgrade.
* **Playbook performance:** sends, opens, clicks, claims and opt-outs per step and variant.
* **Human queue:** tasks with SLA ageing.
* **Prospect drawer:** stage, score and reasons, timeline, contacts, actions.

Manual stage moves, notes and assignment live here as overrides, not as the main workflow.

## 4. Order

| Step | Depends on | Size |
|---|---|---|
| C1 pipeline record | — | done |
| A1 lead compiler + priority score | C1 | done |
| A2 campaign engine + guardrails | A1 | done |
| A7 onboarding funnel (polish, preview images, private claim link, form, verify + publish) + claim assistant | A2 | 4–5 days |
| A6 cockpit + measurement | A2 (grows with each step) | 3 days |
| A3 AI agent layer (copywriter, conversation, recovery, optimizer) | A2, A6 | 4–5 days |
| A8 payment gateway | — (can start any time once E6 is chosen) | 3 days |
| A5 upsell engine + account-manager agent | A2, A8 | 3 days |
| A4 human escalation queue + call outcomes + phone suppression | A3 | 2–3 days |

A6 comes before A3 on purpose: measure the baseline before optimizing it. A4 comes last because agents decide what
reaches people.

**Done means:** a discovery campaign runs and, with no human action, its qualifying businesses get polished private drafts, enter
playbooks ordered by priority score, and receive personalized, behaviour-driven email and SMS within the guardrails.
Owners who click through see their private draft, confirm their details, verify, and are published at claim, with the claim assistant on hand. Replies are answered by the conversation agent.
Escalations reach the human queue with a brief and a script. The cockpit shows the conversion rate from draft emailed to
claimed and attributes each claim to its channel, step, variant and actor (system, AI or human). Claimed owners get
usage-driven upsell offers they can accept and pay for in the portal. An opt-out on any channel is honored everywhere
it should be.

## 5. Decisions

| # | Question | Recommendation |
|---|---|---|
| E1 | Auto-compile volume | Start with a daily cap of 50 new sites, raised as conversion data comes in. |
| E2 | SMS gateway for PH | Pick a local gateway (cost per SMS, sender-ID registration). SMS steps are skipped until one is configured. |
| E3 | Frequency cap and quiet hours | At most 3 touches per prospect per week across channels; no sends 20:00–08:00 Asia/Manila. |
| E4 | Who works the human queue | At least one operator; the queue is sized by the priority threshold. |
| E5 | AI outbound calls | After human calls are working and measured; needs its own legal check and AI disclosure. |
| E6 | Payment gateway | **Decided: PayMongo** for PH clients (GCash, Maya, cards) and **Stripe** for international clients, once the accounts are available. Needed before upsells can close. |
| E7 | Model for live AI conversations | Local LLM for bulk drafting; a stronger hosted model for live sales conversations (quality in Taglish). Cost per conversation to be measured. |
| E8 | Messenger | Meta doesn't allow automated cold messages to Pages: AI answers only people who message first. Cold channels stay email, SMS and calls. |
