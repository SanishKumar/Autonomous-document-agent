# Architecture and decisions

Briefroom is a persistent workspace around the document agent: one team, one FastAPI process, one
SQLite database, and server-local Word files. Its audience is consultants and small teams. The
default preview stays on loopback; accounts and shared review do not automatically create hosting.

## Request paths

```text
Browser → POST /api/jobs → admission + idempotency → async job manager
   │                                                    │
   │                                planner → registered tools → review
   │                                                    │
   ├─ GET /api/documents/:id/events ← SQLite events ←─────┤
   ├─ PUT /api/documents/:id/draft → version transaction  │
   └─ GET /api/documents/:id/export → DOCX builder ←──────┘

API clients → POST /agent → agent service → response + original Word file
```

The legacy endpoint stays synchronous and does not insert into workspace history. The workspace
route returns `202` immediately; its job runs on the application event loop. Model calls use async
HTTP. Export runs in a worker thread so document rendering does not block other HTTP work.

## Storage and consistency

- `documents` holds the current snapshot and a unique submission key.
- `events` is an ordered journal with monotonically increasing cursors.
- `versions` holds immutable structured drafts. Restoring an old draft creates a new version.
- `members`, `sessions`, `invitations` and `team_audit` hold account state and access changes.
- `review_threads`, `review_replies` and `review_decisions` hold attributed, version-bound feedback.
- `review_requests` stores a named handoff per version; a partial unique index prevents duplicate
  active requests. Withdrawing preserves its history and permits reassignment.
- Snapshot, revision and event changes are transactional. Connections are short-lived and closed.
- Edits and approvals supply `expected_version`. An out-of-date writer receives `409`, never a
  silent last-writer-wins overwrite. Saving any edit invalidates human approval.
- Repeated submissions return the original run. Reusing a key for a different brief is rejected.
- Submission keys are scoped to the submitting account, so teammates cannot collide accidentally.
- Exports use version-specific filenames and atomic replacement; titles never become file paths.

SQLite is a pragmatic local repository, not a distributed queue. Keep one Uvicorn worker. Database
calls are short synchronous transactions. A hosted deployment needs a durable worker system and an
asynchronous repository, rather than sharing this process-local scheduler.

## Job lifecycle

```text
queued → running → completed or needs_review
             └──→ failed / cancelled / interrupted

completed → edit → needs_review → human approval → completed
```

A semaphore bounds running jobs; admission bounds queued jobs. The time limit applies once a worker
slot is acquired. Cancellation stops future model calls but cannot refund an in-flight provider
request. On startup, unfinished snapshots are marked interrupted, not silently retried. This avoids
surprise token consumption. Graceful shutdown also preserves interrupted state.

SSE supports `Last-Event-ID` replay, emits keepalives and closes at terminal states. The snapshot
endpoint remains the source of current state. History returns up to 100 events per page, with an
exclusive `after` cursor and a nullable `next_cursor`. The activity view can load subsequent pages
without skipping events or relying on offset positions that change as teammates add activity.

## Model trust boundary

The model returns data, not code. Pydantic validates tool names, dependencies and document structure.
The executor permits a bounded five/six-tool workflow. The planner proposes document-specific tasks;
policy normalizes the graph and controls the optional constraint-resolution step. This is bounded
autonomy, not unrestricted execution.

Drafting and reviewing are separate calls to the configured model, not independent fact-checking
systems. Up to two revisions are allowed. An unresolved low score is retained; there is no score
inflation. A failed revision keeps the last reviewed draft. The UI separates the original AI review
from human approval and makes clear that later edits have not received a fresh AI review.

Reference notes are labeled unverified and fenced in the prompt. This reduces ambiguity, but does
not solve prompt injection. The model has no arbitrary code, filesystem, shell, or browsing tools.
Rendered text is escaped; editing and export do not call an LLM.

## Security boundary

Accounts are invite-only. First-owner setup requires a random local setup key which is not served
over HTTP. Passwords are hashed with Argon2 via `pwdlib`; hashing and verification run off the event
loop with bounded concurrency. Authentication attempts are throttled by IP and IP+email in SQLite.
Unknown accounts use a dummy password hash to avoid an obvious cheap-failure timing distinction.

Opaque session cookies are HttpOnly and SameSite=Strict; the database stores only the token hash,
with a server-side expiry (12 hours by default). Set `SECURE_COOKIES=true` when using HTTPS. Logout,
password changes, deactivation and role changes revoke relevant sessions. Every protected request
reloads current membership; the SSE stream also rechecks the session while running.

Authenticated writes require a per-session CSRF secret in `X-CSRF-Token`. Public account forms
accept JSON only; cross-origin writes are rejected. Session/password/token data is not stored in
browser localStorage. Validation errors omit raw input values to avoid reflecting passwords.
All workspace APIs, legacy generation, and Word downloads require membership. Role checks live on
the server, not just in hidden UI controls. Provider credentials remain in server configuration.

Invitations store a hash of a single-use random secret and bind it to an email and role. Tokens
expire after seven days and travel in a URL fragment, not an HTTP access-log path. Links are shared
manually; possession of a link and knowledge of the invited email is not email-ownership verification.

These choices follow [FastAPI's password-hashing guidance](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/),
the [OWASP session guidance](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html),
and the [OWASP CSRF guidance](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html).
They are implementation choices, not an independent security certification.

Briefs and notes are sent to the configured provider only on submission. Documents, events, and
versions are stored in plaintext on the server. Disk access and backups are the operator's
responsibility. The UI has no analytics, CDN fonts, or external scripts.

## Review consistency

An owner or reviewer can approve or request changes. Editors can draft and discuss but cannot
approve. All members can resolve discussions; this is a collaborative workflow, not enforced
independent sign-off. Decisions and comments capture the reviewed version. The review transaction
checks `expected_version`; approval also checks that there are no unresolved discussions on that
version. A new edit, new discussion, or reopened current-version discussion clears approval.
Older discussions remain available and never silently move to different text. No live text merge
or automatic comment anchoring across revisions is attempted.

Review requests are version-bound too. Inbox state is derived from the current document version,
approval, decisions after the request, and current reviewer access. A new version makes the old
request superseded; an unavailable reviewer is surfaced to the requester. This avoids maintaining
a second mutable copy of approval state that could drift from the document. Requests target one
teammate, but any authorized owner/reviewer may decide; the UI states this explicitly. Personal
inboxes show only assigned/created requests, while document handoff history stays team-visible.
The current implementation returns at most 200 requests and uses explicit refresh, not push alerts.

Browser requests carry a local session-generation check. Clearing or replacing the session
invalidates in-flight responses before they can repaint private content. Route sequencing also
prevents a slow document read from replacing a more recently chosen page. These client checks
improve UI consistency; server-side authentication remains the actual access-control boundary.

## Deployment boundaries

All active members share all documents. There is no tenant boundary, guest link, per-document ACL,
SSO, MFA, password recovery or email verification. The single-process scheduler and synchronous
SQLite repository are deliberate small-team tradeoffs. Server restarts interrupt model runs rather
than retry them at a teammate's expense. Old version tables are backed up before the author-column
migration; other new tables are additive.

Before public deployment: HTTPS, secure cookies, trusted proxy/host configuration, request-body
and admission limits at the edge, backup/restore drills, retention policy, account recovery and
independent security review. Scaling adds a durable queue and operational metrics; separate
organizations require genuine tenant-scoped authorization and storage. None is implied by this
local preview.
