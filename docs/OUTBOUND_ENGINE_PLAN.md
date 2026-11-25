# Outbound onboarding engine — development plan

Status: **in progress** (2026-11-26). C1 built; A1–A6 planned.
Replaces the earlier "sales CRM" plan, which centred on screens where people move prospects by hand. The founder's
direction: an **automated** engine, with people stepping in only where they lift conversion.

## 1. Goal

Turn crawler output into onboarded, paying clients with as little manual work as possible:

```text
discover ─▶ enrich ─▶ score ─▶ generate + publish site ─▶ outbound campaign ─▶ claim (click-to-own) ─▶ upsell
 (crawlers)  (contacts) (BI)     (factory)                  (email · SMS · calls ·    (free owner)         (paid plans,
                                                             AI + human agents)                          verticals)
```

* **Conversion target:** passive claim conversion is typically 1–5% of published sites. The aggressive, multi-channel
  campaign (AI + human agents) aims for **6–15%** in the best case. That is a hypothesis: the engine measures the
  baseline first and reports what each channel, step and message adds (A6).
* **Upsell:** the same engine keeps working after the claim, pushing paid plans and the other verticals.
* **"Aggressive" means** many touches across channels with fast, behaviour-driven follow-up. It does not mean
  ignoring limits: opt-outs are honored on every channel, there are frequency caps and quiet hours, and every
  message carries an opt-out. Breaking these is a legal risk (Data Privacy Act, anti-spam rules) and also lowers
  conversion by burning sender reputation.

## 2. What already exists

| Stage | Today | Gap |
|---|---|---|
| Discover + enrich | Discovery campaigns (OSM, Google, fixture), enrichment waterfall, contact provenance, suppression | — |
| Score | `score_business`: no website, no domain, social presence, phone/email, industry value → `score`, `generate_candidate` | Ignores contact *quality* (verified vs guessed), reviews/ratings, engagement |
| Generate + publish | Factory jobs; **started by hand** (`enqueue` CLI / admin batch) | Not automatic after discovery |
| Outbound | Email only, a fixed Day 0/3/7/14 sequence, enrolled by hand per campaign | No branching on behaviour, no SMS (console only), no calls, no claim-abandon recovery |
| Pipeline record | **C1 (built):** a prospect per published business with an automatic stage + timeline | — |
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

### A1 — lead compiler (automatic intake)
* **Auto-compile:** when a discovery run's enrichment finishes, rescore its businesses and queue site generation +
  publish for new candidates. No human step. It is guarded by `AUTO_COMPILE_ENABLED` and a daily cap
  (`AUTO_COMPILE_DAILY_LIMIT`), so cost and outreach volume stay controlled.
* **Outbound priority score** on the prospect (0–100, with reasons): fit (the existing opportunity score) ×
  reachability (a verified or observed email/phone scores higher than a guessed one; suppressed or invalid contacts
  count as nothing) × signals (engagement so far). It is recomputed on every activity. It decides the order of
  enrollment and which prospects get a human.
* **Readiness rule:** published, unclaimed, not closed, has at least one usable channel. Ready prospects flow to A2.

### A2 — campaign engine (the aggressive outbound)
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

### A3 — AI personalization
Gumaweb's local LLM writes per-business message variants and call scripts from the business profile and its
generated site, inside templates with guardrails (facts only from the profile, required opt-out, length limits).
Each playbook step can carry A/B variants; A6 measures which converts. Falls back to the plain template when AI is off.

### A4 — human in the loop
People get only the moments that need them, as tasks in a queue ordered by priority score: hot leads (clicked or
started a claim), replies, callbacks, high-value prospects. The queue offers a one-screen call view: script (A3),
site link, claim link, contacts. Call outcomes are logged through `apply_call_outcome()` with the dialer seam's
outcome codes:
* interested → claim-link task/email;
* email captured → stored as a confirmed contact and becomes reachable by email;
* not interested → lost with a cooldown;
* do not call → blocks every channel;
* wrong number → contact marked invalid and flagged; the public number on their site isn't cleared.

Phone suppression is added here. When GumaDial is ready, its outcomes arrive through the same function
(`source=dialer`); see the parked `OUTREACH_DIALER_BRIDGE_PLAN.md`.

### A5 — upsell engine
After a claim, prospects move to upsell playbooks driven by usage signals: site traffic, leads received, bookings,
missed calls, unanswered chats. Examples: *leads arriving and no CRM → Business plan*; *traffic but no own domain →
custom domain*; *missed calls → Voice AI receptionist*. The same engine, guardrails and measurement apply; `won` and
plan changes come from billing.

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
| A1 lead compiler + priority score | C1 | 2–3 days |
| A2 campaign engine + guardrails | A1 | 4–5 days |
| A4 human queue + call outcomes + phone suppression | A2 | 2–3 days |
| A6 cockpit + measurement | A2 (grows with each step) | 3 days |
| A3 AI personalization + A/B | A2, A6 | 2–3 days |
| A5 upsell engine | A2 | 2–3 days |

A6 comes before A3 on purpose: measure the baseline before optimizing it.

**Done means:** a discovery campaign runs and, with no human action, its qualifying businesses get sites, enter
playbooks ordered by priority score, and receive behaviour-driven email and SMS within the guardrails. Hot prospects
appear in the human queue with a script. The cockpit shows the conversion rate from published to claimed and
attributes each claim to its channel and step. Claimed owners enter upsell playbooks. An opt-out on any channel is
honored everywhere it should be.

## 5. Decisions

| # | Question | Recommendation |
|---|---|---|
| E1 | Auto-compile volume | Start with a daily cap of 50 new sites, raised as conversion data comes in. |
| E2 | SMS gateway for PH | Pick a local gateway (cost per SMS, sender-ID registration). SMS steps are skipped until one is configured. |
| E3 | Frequency cap and quiet hours | At most 3 touches per prospect per week across channels; no sends 20:00–08:00 Asia/Manila. |
| E4 | Who works the human queue | At least one operator; the queue is sized by the priority threshold. |
| E5 | AI outbound calls | After human calls are working and measured; needs its own legal check. |
