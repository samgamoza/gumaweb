# Outreach × GumaDial bridge — development plan

Status: **parked** (2026-11-26). GumaDial isn't ready; work resumes once it is.

## Resume here

What already exists in Gumaweb (the hook):
* `app/domains/dialer/`: the `Dialer` protocol and v1 contract types (`DialerContact`, `DialerEvent`,
  `CallOutcome`, `PushStatus`), `to_e164()`, `external_ref()`, and `NullDialer`.
* `providers.dialer` (composition root), selected by `DIALER_PROVIDER` (only `none` today).
* The sales CRM logs calls by hand as activities; when a dialer is connected, its outcomes become the same
  activities (see the CRM plan).

Checklist when GumaDial is ready:
1. In GumaDial: G0 (repo + green suite) and approve ADR-0004 (D1, D3).
2. Re-check §2 against GumaDial's code; it was written against GumaDial as of 2026-09-24.
3. GumaDial G1–G4. Gumaweb: add `GumaDialDialer` in `app/domains/dialer/`, allow
   `DIALER_PROVIDER=gumadial`, then W1–W6 (W0's CSV export is optional by then).
4. Decide D2, D4–D6.

Goal: make outreach multi-channel. Gumaweb finds businesses, builds their sites and runs email; GumaDial
(`D:\All Apps\gumadial`) is a human-operated calling platform. Connect them so the businesses email can't
reach get a phone call, what's learned on the call flows back into Gumaweb, and both systems keep one
do-not-contact truth.

## 1. Why this matters

* **Email reaches a minority of the funnel.** Outreach enrolls only businesses with `Business.email`
  (`outreach_service.launch`). Most PH SMBs found by discovery have a phone and no email or website
  (guma_os measured 0 of 19 with a scrapeable website). Today those published sites never get pitched.
* **A call can unlock email.** An owner who says "send it to my email" gives us the strongest contact we
  can have (`user_supplied`, promotable), which then enters the normal email sequence.
* **GumaDial already planned for this.** Its ADR-0004 (*proposed*, awaiting founder approval) defines
  exactly this integration: two narrow data contracts, no shared database, GumaDial stays standalone,
  and only GumaDial decides whether a call may be placed.

## 2. What exists today (checked in code)

| | Gumaweb | GumaDial |
|---|---|---|
| Stack | FastAPI + Postgres job queue, Next.js admin | Fastify + Prisma + BullMQ/Redis, Next.js, Asterisk |
| Leads | `Business` (+ `business_contacts` provenance), phone stored as digits `63917…` | `Contact` (firstName, lastName, `phoneE164`, status `PENDING_APPROVAL → APPROVED/DENIED`), unique per org+phone |
| Campaigns | `OutreachCampaign`, channel enum already has `voice` (unused; `create` rejects non-email) | `Campaign` + `ContactList`s, pacing, retries, calling window (UTC hours) |
| Outcomes | `OutreachEvent` (email_sent, opened, clicked, claim_*, unsubscribed) | `Disposition`: CONNECTED_INTERESTED, CONNECTED_NOT_INTERESTED, NO_ANSWER, VOICEMAIL, WRONG_NUMBER, DO_NOT_CALL, CALLBACK_REQUESTED (+ `Callback.scheduledFor`) |
| Do-not-contact | email / whole domain (`outreach_suppressions`) | phone (`SuppressionEntry`, sources MANUAL, DO_NOT_CALL_DISPOSITION, FEDERAL_DNC) |
| Machine API | customer API keys + signed outbound webhooks (`integration_service`) | **none**: users log in with session cookies; only telephony adapters post signed events |
| Event stream | outbox events | call events published to Redis `org:{id}:events` (fire-and-forget); **dispositions are not published** |
| Real calls | — | code-complete for Asterisk, **switched off** (`TELEPHONY_ADAPTER=mock`) |
| Repo | GitHub `samgamoza/gumaweb` | **no git remote; 37 uncommitted files** on `master` |

## 3. Decision: a bridge, not a merge

| Option | Verdict |
|---|---|
| Build calling inside Gumaweb | No. Telephony, pacing, agent console and call compliance are GumaDial's whole product. Rebuilding them is months of work. |
| Share a database | No. Breaks GumaDial ADR-0001/0004, couples deploys and makes compliance ownership unclear. |
| **API bridge with a dialer adapter in Gumaweb** | **Yes.** GumaDial gains a small Integration API. Gumaweb gains a `Dialer` interface with a GumaDial adapter (plus a CSV-export adapter that works today). "Internal" vs "bridge" becomes an adapter choice, and another dialer can be plugged in later. |

Division of responsibility (from ADR-0004, kept as is):

* **Gumaweb decides who is worth calling** and supplies the data lawfully (discovery provenance, suppression).
* **GumaDial decides whether and when a call may happen** (`evaluateCallPolicy`: DNC, calling window,
  human approval, retries, callbacks). Nothing Gumaweb sends can authorize a call; contacts arrive as
  `PENDING_APPROVAL` and a supervisor approves them.
* **Gumaweb owns every non-voice follow-up** (email, later SMS) by consuming call outcomes.

```text
 Gumaweb                                             GumaDial
 ───────                                             ────────
 discovery → score → site published
 voice campaign picks eligible businesses
   │  POST /v1/integration/contact-batches  ───────▶ ContactList (PENDING_APPROVAL)
   │  (externalRef, company, +63 E.164, score,          │ supervisor approves
   │   dossier: site URL, claim link, why)              ▼
   │                                                  campaign / agent calls
   │                                                  evaluateCallPolicy (DNC, window)
   │  GET /v1/integration/outcomes?after=cursor ◀─── Disposition (+ captured email, callback)
   ▼
 outcome sync job: events, contacts, suppression,
 next step in the cadence (e.g. email claim link)
   │  POST /v1/integration/suppressions  ──────────▶ SuppressionEntry (phone DNC)
```

## 4. The contract (v1)

Auth: `Authorization: Bearer <integration token>`. GumaDial stores only a hash. A token is bound to one
organization and to the scopes `contacts:write`, `outcomes:read`, `suppressions:write`. It is not a user
session, and its actions are audited as `integration:<name>`.

**Push contacts:** `POST /v1/integration/contact-batches`
```json
{ "batchRef": "gw:campaign:<uuid>:1", "listName": "Gumaweb — Angeles restaurants",
  "contacts": [ { "externalRef": "gw:business:<uuid>", "companyName": "Santos Plumbing",
                  "firstName": null, "phoneE164": "+639171234567", "timezone": "Asia/Manila",
                  "score": 82, "dossier": { "siteUrl": "...", "claimUrl": "...?ref=<token>",
                  "industry": "plumbing", "city": "Angeles", "reasons": ["no website", "4.6★ 31 reviews"] } } ] }
```
Idempotent on `batchRef`. The response reports each row as `created`, `duplicate` (already known: the
external ref is updated), `suppressed` or `invalid`. Up to 500 rows per request.

**Pull outcomes:** `GET /v1/integration/outcomes?after=<cursor>&limit=200`. The feed returns, ordered,
`disposition.recorded` (code, notes, capturedEmail?, ownerName?, callbackAt?, attemptCount, externalRef),
`contact.reviewed` (approved/denied) and `suppression.added` (phone, source), plus `nextCursor`. The cursor
is opaque (`createdAt` + `id`). Replaying from an old cursor is safe because Gumaweb dedupes on event id.

**Push suppressions:** `POST /v1/integration/suppressions`, a list of `{ phoneE164, reason }`, stored with a
new source `PARTNER`. It is idempotent.

**Why pull, not webhooks, first:** dispositions aren't on GumaDial's event stream, and that stream is Redis
pub/sub, which drops messages when no one is listening. Pull needs no outbox and no new GumaDial worker,
and survives either side being down. Gumaweb asks; GumaDial never has to reach Gumaweb (GumaDial runs on
the LAN/Proxmox). Signed push webhooks are a later step if minute-level latency ever matters.

## 5. Steps

Two tracks. **G** is GumaDial work (proposed there as *Mission 013: Integration API*, implementing ADR-0004);
**W** is Gumaweb work. One PR per step, with tests on both sides. Shared JSON fixtures of every contract
payload live in both repos and are contract-tested.

### G0 — put GumaDial under version control (prerequisite)
Commit the 37 uncommitted files in reviewed chunks (HANDOFF already asks for this), create a private
GitHub repo, push. Run `pnpm build && pnpm typecheck && pnpm test` and record what's red (`transfer.test.ts`
is known red). *Needs your OK for the new repo.*

### W0 — quick win with no GumaDial changes: call-list CSV export
Admin → Outreach → "Export call list": eligible businesses (published, unclaimed, has phone, not
suppressed) as GumaDial's CSV format (`firstName,lastName,phone,timezone`). The business name goes in
firstName and the city in lastName, because GumaDial has no company field yet. Files are split into 100-row
chunks, GumaDial's import limit, and phones are formatted `+63…`. Agents can start calling the no-email
segment today; outcomes come back manually. This becomes the `CsvExportDialer` adapter later. *~1 day.*

### G1 — integration tokens + bearer auth
New `IntegrationClient` table (org-scoped, hashed token, scopes, last used, revoked). A Fastify plugin
resolves bearer tokens separately from the session actor, so no route accepts both by accident. There is an
admin page to create and revoke tokens (shown once). Plus rate limiting and an audit action. Tests: wrong
org, revoked token, missing scope, token never accepted on user routes.

### G2 — contact-batch ingest + intelligence fields
Migration on `Contact` (all nullable, additive, per ADR-0004): `externalSource`, `externalRef`
(unique per org+source+ref), `companyName`, `intelligenceScore`, `intelligenceDossier`,
`intelligenceUpdatedAt`. Batch endpoint as in §4. It reuses import's validation, dedupe and suppression
check, and contacts always land `PENDING_APPROVAL`. Approval review and the agent console show the company
and a briefing panel (site link, claim link, reasons). Hopper ordering uses the score only as a tiebreak
hint. Static-safety test: `evaluateCallPolicy` never reads an intelligence field.

### G3 — outcomes feed + structured capture on the disposition form
The cursor feed from §4. The disposition form gains two optional fields, shown only for contacts with an
`externalSource`: **email the owner gave** (validated) and **owner name**. This is data capture, not a new
channel, so ADR-0004 §6 holds. Tests: ordering, cursor stability under concurrent inserts, org isolation.

### G4 — suppression intake
`POST /v1/integration/suppressions` and the `PARTNER` source. DO_NOT_CALL dispositions already create
suppression entries, and they appear in the G3 feed.

### W1 — dialer adapter + settings
`app/domains/dialer/`: a `Dialer` protocol (`push_batch`, `fetch_outcomes(cursor)`, `push_suppressions`,
`health`) with `GumaDialDialer` (httpx), `CsvExportDialer` (W0) and `NullDialer` (the default, so
standalone Gumaweb is unchanged). Config: `DIALER_PROVIDER`, `GUMADIAL_BASE_URL`, `GUMADIAL_TOKEN`, and
`GUMADIAL_ALLOW_PRIVATE` (GumaDial is on the LAN, and `safe_fetch` rejects private addresses unless
allowed, the same pattern as `WEBHOOK_ALLOW_PRIVATE`). `integration_cursors` table. The admin status card
shows connection test, last sync and lag.

### W2 — phone suppression in Gumaweb
`SuppressionKind.PHONE` (normalized with `normalize_phone`), a `not_suppressed_phone()` SQL helper, the
admin page and CLI (`suppress add +63917… --phone`), and the scrub job extended to skip queued call pushes.
Every new phone suppression is forwarded to GumaDial (W4).

### W3 — voice campaigns
Enable `OutreachChannel.VOICE`. Targets: published, unclaimed, has phone, phone not suppressed, not in a
call cooldown. By default it takes only businesses **without** a usable email. Each enrolled business
gets an `OutreachMessage(channel=voice)` with its own tracking token, so a claim that follows a call is
attributed to the call (`claim_url?ref=<token>` goes in the dossier). A `push_to_dialer` job sends
batches; `dedupe_key=dialer-push:<campaign>`.

### W4 — outcome sync
A worker tick, `sync_dialer_outcomes` (single flight), pulls the feed and applies each event once
(`outreach_events.external_id`, unique). Mapping:

| GumaDial outcome | Gumaweb does |
|---|---|
| CONNECTED_INTERESTED | event `call_interested`; admin notification; if an email was captured, send the claim-link email now |
| captured email (any outcome) | `ContactService.record(user_supplied)`: promoted to `Business.email` if empty, and becomes eligible for the email sequence |
| CONNECTED_NOT_INTERESTED | event; 90-day cooldown from voice campaigns |
| NO_ANSWER / VOICEMAIL | event only (GumaDial owns retries) |
| CALLBACK_REQUESTED | event with `callbackAt` (GumaDial owns the callback) |
| WRONG_NUMBER | `business_contacts` phone → `invalid`; flag the business for review. `Business.phone` is not cleared automatically, because it's on their public site |
| DO_NOT_CALL | phone suppression in Gumaweb; skip all queued outreach to that business (see decision D2) |
| contact denied | event; not re-pushed for that campaign |

Gumaweb's own phone suppressions go the other way via `push_suppressions`.

### W5 — cross-channel cadence
Sequence steps gain `channel` (`email` | `voice`) and an optional condition (`if_not_engaged`). Examples:
*email day 0 → call day 2 if not opened/clicked → email day 7*; for no-email businesses: *call → claim
email as soon as an email is captured*. The admin campaign editor shows the steps and the channel mix.

### W6 — reporting
Per-channel funnel: pushed → approved → reached → interested → claimed, with cost per claim (calls' agent
time comes from GumaDial reports). The business timeline shows calls next to emails. Later, call outcomes
can feed the lead score (ADR-0004's feedback loop).

### G5 — later, only if needed
Signed push webhooks from a durable outbox, for lower latency.

## 6. Order and size

| Step | Repo | Size | Depends on |
|---|---|---|---|
| G0 version control | GumaDial | ½ day | your OK |
| W0 CSV export | Gumaweb | 1 day | — (ships value now) |
| G1 tokens | GumaDial | 1–2 days | G0 |
| G2 batch ingest + fields | GumaDial | 2–3 days | G1 |
| G3 outcomes feed + capture | GumaDial | 2 days | G1 |
| G4 suppression intake | GumaDial | ½ day | G1 |
| W1 adapter + settings | Gumaweb | 1–2 days | contract fixtures |
| W2 phone suppression | Gumaweb | 1 day | — |
| W3 voice campaigns | Gumaweb | 2 days | W1, W2, G2 |
| W4 outcome sync | Gumaweb | 2 days | W1, G3, G4 |
| W5 cadence | Gumaweb | 2–3 days | W3, W4 |
| W6 reporting | Gumaweb | 1–2 days | W4 |

About 3 weeks of focused work. W0 and W2 can start immediately. The G track and W1 can proceed in parallel
once the contract fixtures are agreed (first PR of each track).

**Done means:** a business with no email is pushed, approved by a supervisor, called through the mock
adapter; the agent records "interested" + an email. Within one sync, Gumaweb shows the call on the
business, has stored the email as `user_supplied`, has sent the claim email, and attributes the claim to
the call. A DO_NOT_CALL in either system blocks the other. All of this works on SQLite and Postgres in
Gumaweb, and GumaDial's suite stays green. Gumaweb with `DIALER_PROVIDER=none` behaves exactly as today.

## 7. Decisions for you

| # | Question | Recommendation |
|---|---|---|
| D1 | Create a private GitHub repo for GumaDial and commit its 37 pending files? | **Yes, first.** Building an integration on uncommitted code is too risky. |
| D2 | What does a refusal block? | **DNC on a call blocks all channels** (an owner saying "stop" means the company, not the phone). **An email unsubscribe blocks email only.** An explicit "do not contact" entry blocks both. |
| D3 | Approve GumaDial ADR-0004 (currently *proposed*)? | **Yes.** This plan implements it unchanged. |
| D4 | Real calling: switch Asterisk on, trunk cost to PH numbers, calling hours | Stay on **mock** through W4. Before live calls: legal check under the Data Privacy Act for cold B2B calls, a 9:00–18:00 Asia/Manila window (GumaDial stores UTC hours: 01–10), and the trunk's PH rates. |
| D5 | Who makes the calls? | Agents and supervisors are GumaDial users. The plan assumes at least one supervisor to approve batches. |
| D6 | Network | Gumaweb's worker must reach GumaDial's API (LAN, or Tailscale if Gumaweb is hosted elsewhere). GumaDial never calls Gumaweb in v1. |

## 8. Review pass: what changed from the first draft

The first draft was checked against both codebases. Changes:

1. **Pull instead of push for outcomes.** The draft used webhooks from GumaDial's event stream. In code,
   dispositions are never published, and the stream is fire-and-forget Redis pub/sub. A cursor feed over
   the `Disposition` table is simpler and loses nothing.
2. **Gumaweb no longer schedules calls.** The draft had Gumaweb deciding call times. GumaDial already owns
   retries, callbacks, pacing and calling windows, and its rule is "humans authorize". Gumaweb now only
   picks *who* and reacts to *what happened*.
3. **Phone suppression added to Gumaweb (W2).** The draft synced DNC one way. Gumaweb's suppressions are
   email/domain only, so it couldn't hold or forward a phone DNC.
4. **Captured email made a first-class outcome (G3, W4).** This is the biggest win: it turns the no-email
   majority into email-reachable leads. The draft treated calls as a dead end.
5. **G0 and W0 added.** GumaDial has no remote and pending changes; W0 delivers value before any API exists.
6. **Format gaps fixed:** Gumaweb stores phones as `63917…` and GumaDial's CSV defaults to US parsing, so
   the bridge always sends `+63…` E.164. GumaDial has no company field (G2 adds `companyName`; W0 uses
   firstName as a stopgap). Imports are capped at 100 rows (W0 chunks).
7. **`WRONG_NUMBER` does not clear `Business.phone`.** It's the public number on their site; the same
   lesson as Step 6's `Business.email` fix.
