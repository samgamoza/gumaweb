# Sales CRM (Guma OS's own pipeline) — development plan

Status: **proposed** (2026-11-26).

Not to be confused with the **customer CRM** (portal → Leads & CRM, `crm_service.py`), which business owners use
for *their* leads. This CRM is for us: the businesses Guma OS is pitching, from published site to paying customer.

## 1. Problem

The pipeline exists, but only as scattered facts across admin screens:

| Fact | Where it lives today |
|---|---|
| found, scored, site published, claimed | `Business.status` (Businesses, Discovery) |
| emailed, opened, clicked, unsubscribed | `outreach_events` (Outreach: campaign totals only) |
| claim started / approved / rejected | `claims` (Claims) |
| paying, plan, canceled | `customers`, `subscriptions` |
| contacts and where they came from | `business_contacts` (Contacts panel) |

Nobody can answer "who should I follow up with today?", there's nowhere to write a note or log a phone call,
no owner per prospect, and no single timeline for one business.

## 2. Design

**A prospect is a business**: no duplicate records. Three new tables:

* `prospects` (1:1 with `businesses`): `stage`, `owner_user_id`, `score` + `score_reasons`, `last_touch_at`,
  `stage_changed_at`, `lost_reason`, `cooldown_until`. Created when a site is published, or by hand.
* `prospect_activities`: the timeline. `type`, `source` (`system` | `manual` | `dialer`), `actor_user_id`,
  `data` (JSON), `occurred_at`, `external_id` (unique, nullable: makes dialer and backfill replays no-ops).
* `prospect_tasks`: follow-ups. `title`, `due_at`, `assignee_user_id`, `done_at`.

**Stages:**

```text
new ─▶ contacted ─▶ engaged ─▶ conversation ─▶ claimed ─▶ won
                                                          (paying)
                              any stage ─▶ lost | do_not_contact
```

| Stage | Entered automatically when | Or by hand |
|---|---|---|
| new | the site is published | — |
| contacted | the first outreach email is sent | yes |
| engaged | an open, click or site visit from outreach | yes |
| conversation | a call is logged as connected, or a claim is started | yes |
| claimed | a claim is approved | — |
| won | a paid subscription starts | — |
| lost | a call is logged as "not interested" (with a cooldown) | yes, with a reason |
| do_not_contact | a suppression with reason `requested`, `complaint` or `legal` matches its email, domain or phone, or a call is logged as "do not call" | yes |

Automatic moves only go forward and never leave `lost`/`do_not_contact`. A person can move a prospect anywhere,
and every move is an activity with an audit entry. A canceled subscription after `won` adds a `churned` activity
and a task, not a stage change.

**One place records touches.** `ProspectService.record(business, type, source, data, external_id)` is called
from the existing event points: outreach send/open/click/unsubscribe, claim start/approve/reject, publish,
subscription changes and suppression. It writes the activity, advances the stage, updates `last_touch_at`
and rescores. Callers don't need to know about stages.

**Calls: the GumaDial hook.** A manual "log call" uses the dialer seam's `CallOutcome` codes, and goes through
the same `ProspectService.apply_call_outcome()` that a connected dialer will use later (`source=dialer`,
`external_id` = the dialer event id). The rules are written once:

| Outcome | Effect |
|---|---|
| INTERESTED | stage ≥ conversation; task "send claim link" due today |
| email captured (any outcome) | `ContactService.record(user_supplied)`: promoted to `Business.email` if empty, so the business becomes eligible for email outreach |
| NOT_INTERESTED | `lost`, 90-day cooldown from outreach |
| NO_ANSWER / VOICEMAIL | activity only |
| CALLBACK_REQUESTED | task at the callback time, assigned to the caller |
| WRONG_NUMBER | phone contact marked `invalid`; task "check number". `Business.phone` isn't cleared (it's on their public site) |
| DO_NOT_CALL | phone suppression + `do_not_contact`; queued outreach for the business is skipped |

**Phone suppression** (`SuppressionKind.PHONE`) is added here because logged calls need it; it is the W2 step of
the parked dialer plan, so that plan gets shorter.

**Score**: an explainable 0–100 "how warm" score built from touches and their recency, plus the discovery
lead score. It is the same approach as the customer CRM's `score_lead`, with its own weights:
claim started > call interested > click/visit > open > sent, decaying over 30 days. Crossing into *hot*
creates a task for the owner.

**Outreach respects the CRM**: campaign targeting skips prospects in `lost` (until the cooldown ends),
`do_not_contact`, `claimed` and `won`, and can filter by stage and owner.

## 3. Screens (admin → **Pipeline**)

* **Board**: columns per stage with counts. Filters: owner, city, industry, score, "has email", "has phone".
  Drag to change stage (asks for a reason when moving to lost).
* **List**: sortable table with the same filters; bulk assign owner, bulk change stage, add to an outreach
  campaign.
* **Prospect drawer**: business card (site link, contacts panel, claim status, plan), timeline, then
  actions: add note, log call (outcome, notes, captured email/owner name, callback time), add task, change
  stage, assign.
* **My day** (the Pipeline home): my tasks due today/overdue, my hot prospects, recently engaged prospects
  with no owner.

Roles: admin and operator can edit; readonly can view.

## 4. Steps (one PR each, tested on SQLite and Postgres)

| Step | What | Size |
|---|---|---|
| C1 | Tables + migration 0011 with **backfill** (a prospect for every published business; activities from existing outreach events, claims and subscriptions, with stages computed from them); `ProspectService.record` wired into outreach, claims, publishing, billing and suppression | 2–3 days |
| C2 | API: list/board counts/filters, detail + timeline, notes, tasks, stage change, assign, bulk actions | 2 days |
| C3 | Calls and phone suppression: `apply_call_outcome`, `SuppressionKind.PHONE` (+ scrub, CLI, admin page), outreach targeting respects stage and cooldown | 2 days |
| C4 | Admin UI: My day, Board, List, Prospect drawer | 3 days |
| C5 | Score + hot-prospect tasks, funnel report (stage conversion, time in stage, per owner) | 1–2 days |

About 2 weeks. C1 is the foundation; C2 and C3 can follow in either order; C4 needs C2.

**Done means:** after C1's backfill, every published business appears with a stage that matches its history.
An operator logs a call ("interested", captured email) from the drawer. The business's email is filled from
the call, the stage moves to conversation, a "send claim link" task appears in My day, and the next outreach
campaign can reach it. A "do not call" blocks every channel. Existing outreach, claims and billing behave
exactly as before.

## 5. Decisions

| # | Question | Recommendation |
|---|---|---|
| R1 | Are the stages above right? | Yes as listed; `claimed` (free) and `won` (paying) kept separate because conversion to paid is the business. |
| R2 | Tasks table, or one "next action" per prospect? | **Tasks table**: callbacks and follow-ups pile up, and My day needs them. |
| R3 | Should a prospect exist before its site is published? | **No** (create on publish, or by hand). Discovery can produce thousands of rows; the pipeline should hold the ones we can pitch. |
| R4 | Does an email unsubscribe make a prospect `do_not_contact`? | **No**: `unsubscribed` and `bounced` block email only (an activity is recorded; calls are still allowed). `requested`, `complaint`, `legal` or a logged "do not call" block everything. Same rule as the parked dialer plan's D2. |
