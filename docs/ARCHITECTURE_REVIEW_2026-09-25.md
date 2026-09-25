# Architecture review — 25 September 2026

## Follow-up corrections

Profile-check network errors, 403/429/5xx, unknown markup and unrelated redirects
are inconclusive, not confirmed expiry. They now retain the session and return
`session_verification_unavailable`; only positive login evidence records expiry.

File references now strip only known auth parameters while preserving resource
selectors, duplicate keys, encoding and blank values. This prevents different
query-selected files from sharing an ID. IDs are URL-derived and stable across
known signature rotation only; changing the resource URL can change the ID.
No authenticated `read_file` resolver is implemented or advertised.

Verified: 272 Python tests from Working/.venv and two Node browser-component tests
passed. Node exists at the bundled runtime path documented in the handoff; it is
not necessarily on PATH. The handoff test/preview commands now use Working/.venv.

## Implementation status (updated later on 25 Sep)

| Item | Status | Evidence |
|---|---|---|
| 1 Version control | **Done for Working**: private git repo in `Working/` (commits `06a55d0`…). Approved snapshots/tags not changed (Approved is out of scope). | `git log` |
| 2 Own runtime | **Done**: `Working/.venv` + `uv.lock`, constrained to Approved's `requirements.lock`. | tests run from `.venv` |
| 3 Signed URLs | **Done**: opaque render-stable `file_id`; expiring links omitted from task and class-file output. | tested; replayed on the saved Biology page (3 signed PDFs → name + file_id) |
| 4 Connection reuse / lock | **Done**: one pooled client per account, 4 concurrent calls. | tested (reuse, rotated cookies, bounded concurrency) |
| 5 Retry / politeness | **Done**: one jittered retry for connect errors, 502/503/504, short 429 Retry-After. | tested |
| 6 One list engine | **Done**: `collections.collect` handles totals; get_classes/get_tasks use it. | tested |
| 7 One entry point | **Done in Working**: single `/api/tools/{name}` route; `ToolSession.classes` is a thin alias kept for host compatibility. | tested |
| 8 One definition style | **Done**: all 12 tools via `contracts.definition`, with `title` and `openai/toolInvocation` status text. | tested |
| 9 MCP SDK 2 / spec 2026-07-28 | **Deferred**: must move together with the Approved host (SDK 2 replaces lowlevel decorators and `httpx` with `httpx2`); migrating Working alone would break promotion parity. | — |
| 10, 13 OAuth/CIMD, host session scan | **Not changed**: Approved host code, out of scope. | — |
| 12 Session lifetime | **Instrumented**: confirmed expiry records `session.expired_confirmed` with age in seconds (from ToolSession creation). Needs live data. | tested |
| 14 Blocking I/O | **Done in Working**: report/login exports via `asyncio.to_thread`. | tested |
| 15 Evidence capacity | **Done**: `ReportWriter.status()`; workbench warns when nearly full / full. | tested |
| 11, 16 | No change needed / scale guidance only. | — |

Not live-verified: every change above. Run from Working with
`.venv/bin/python -m pytest -q` (259 passed).

For promotion, note: `ToolSession` now owns a long-lived client, so a host must
call `aclose()` when it drops a session (the current Approved host deletes
sessions without closing; its own snapshot is unaffected until promotion).

Scope: Working (12-tool catalogue after the Codex migration and two review passes),
the Approved test host (read-only), and the legacy `multi-user` repository as
comparison. `ARCHITECTURE_REVIEW.md` (7 Sep) reviews the legacy system and is
historical. Evidence types are labelled: **measured**, **tested** (automated),
**read** (source inspection), **researched** (external docs).

## Verdict

The layering is right and should be kept: bounded same-school transport →
pure page parsers → narrow tools with explicit output contracts → thin MCP
adapter. Failures stay failures; nothing silently truncates. The weaknesses are
not in that core but around it: no version control, a borrowed runtime, one
serialized connection per call, no retry or outbound rate control, a
file-reference model that leaks expiring credentials, and a hosting layer that
has fallen behind the 2026 MCP/OpenAI auth guidance. Parser speed is not a
problem (measured: ~61 ms to parse and compact a 200 KB task page; median live
call ~500 ms, almost all network).

## Measured baseline (Sep 24–25 live reports, developer mode)

| Operation | Calls | Median | Max | Requests/call |
|---|---|---|---|---|
| get_task | 58 | 502 ms | 827 ms | 1 |
| get_tasks | 19 | 486 ms | 734 ms | 1 |
| get_classes | 3 | 1495 ms | 2498 ms | 2 |
| login | 2 | 1729 ms | 1960 ms | 3 |

Sep 24 audit (old MYP classes): 14/18 task lists and 55/58 task details
succeeded; the 7 failures were `layout_changed` / `unsupported_task_layout`
and were not attributable to IDs (target logging was added afterwards). The
account's enrolment then changed (15 classes replaced by 10), so those pages
may no longer be reproducible.

## Priority 1 — do next

1. **Put V2 under version control.** (read) Neither `ManageBac-V2` nor `Working`
   is a git repository. Two agents edited Working concurrently this morning, and
   the only rollback was an ad-hoc copy. "Approved" is a set of directory copies.
   → `git init` a *private* repo at `ManageBac-V2/` with `.gitignore` for
   `Test Reports/`, `__pycache__`, state and keys. Replace approved snapshot
   folders with tags (`approved/02-get-classes`, …) and let `deploy_host.py`
   publish from a tag. Reports and private state stay outside git.
2. **Own the runtime.** (read) Working runs on the legacy repo's venv (Python
   3.14, mcp 1.27.2) with an unpinned `pyproject.toml`; Approved has its own
   `requirements.lock`. → Create `Working/.venv` with `uv`, commit `uv.lock`, and
   run tests from it. Keep `mcp>=1.27,<2` until the planned migration (item 9).
3. **Stop putting signed download URLs in model output.** (measured) CloudFront
   links (`Expires`/`Signature`/`Key-Pair-Id`) expired ~2 h after rendering, and
   `/attachments/…` links return 403 without the school session, so ChatGPT
   cannot open them and they sit in transcripts as bearer credentials. → Return
   stable ManageBac-derived `file_id`s plus the portal page `open_url`; resolve
   downloads server-side in a future `read_file` tool (design in the file-access
   research, 25 Sep).
4. **Reuse one HTTP connection per account, and lock only cookie state.**
   (read) `ToolSession.call` creates a new `httpx.AsyncClient` per call (new TLS
   handshake every time) and holds one account lock for the entire call, so
   parallel tool calls from ChatGPT queue behind each other. → Keep one
   long-lived client per `ToolSession` (bounded pool, e.g. 4 connections, HTTP/2
   off), share its cookie jar, and hold the lock only while reading/writing
   cookies. Close it when the session expires.
5. **Bounded retry and outbound politeness.** (read) Any transient 502/503/504
   or connect error becomes a user-visible failure; there is no per-school rate
   control. → In `pages.fetch_html`: one retry with jittered backoff for GET on
   connect errors and 502/503/504; honour `Retry-After` on 429 once if it fits
   the remaining budget; otherwise return `rate_limited`. Add a per-origin
   semaphore (e.g. 4 concurrent) and a small token bucket per account.

## Priority 2 — structure and code quality

6. **One list-collection engine.** (read) Three near-identical loops remain:
   `tools/classes._collect` (with source-total checks), `tools/tasks.get_tasks`
   (with its own totals) and `sources/managebac/collections.collect` (no totals).
   → Extend `collect` so a parser may return `(rows, total, next)`; enforce
   duplicate, page, record and total checks once. Then `get_classes` and
   `get_tasks` become ~10-line tools and `tools/classes.py` can use
   `retrieval.execute` like every other tool (keep its larger documented limits
   as parameters).
7. **Two entry points for the same call.** (read) `ToolSession.classes` duplicates
   `ToolSession.call('get_classes')`, and `onboarding/app.py` has a separate
   `/api/tools/get_classes` route beside `/api/tools/{tool_name}`. → Remove the
   special cases once Approved no longer needs `session.classes` (promotion
   step), keeping one dispatch path and one report writer.
8. **Tool definitions in one style.** (read) `tools/classes.py` builds its `Tool`
   by hand; `get_tasks`, `get_task`, `get_class_files` embed schemas inline; the
   new tools use `contracts.definition` + `output_schemas.py`. → Move all output
   schemas into `output_schemas.py` and build every definition with
   `contracts.definition`; add `title` and short `_meta["openai/toolInvocation/…"]`
   status strings there once, for all tools.

## Priority 3 — platform alignment (researched)

9. **MCP 2026-07-28 and Python SDK 2.x.** The spec removed protocol sessions,
   the `initialize` handshake and SSE resumability; requests carry version and
   capabilities in `_meta`; `server/discover` is mandatory; results gain
   `resultType`; list results gain `ttlMs`/`cacheScope`. SDK 2.2.0 implements
   this but renames fields to snake_case, replaces lowlevel decorators with
   `on_*` handlers, and swaps `httpx` for `httpx2`. Our adapter is small
   (`tools/server.py`), so the migration is contained: plan it as one reviewed
   step together with the transport's move to `httpx2`, after items 1–2.
   Approved already runs stateless Streamable HTTP, which is the right base.
10. **OAuth on the hosting layer.** The spec now deprecates Dynamic Client
    Registration in favour of Client ID Metadata Documents; OpenAI (21 Aug 2026)
    publishes a stable CIMD client ID and a stable redirect
    (`https://chatgpt.com/connector_platform_oauth_redirect`) when the
    authorization server supports RFC 9207 `iss`. Approved enables DCR only.
    → When the host is next changed: add CIMD support and
    `authorization_response_iss_parameter_supported`, keep DCR for compatibility,
    declare `securitySchemes` on every tool (currently only get_classes), and add
    an `openai/profile` read-only `get_profile` tool returning an opaque stable
    account ID for multi-account support.
11. **Result framing.** Errors now return text + `isError` (fixed). Successful
    results send `structuredContent` with empty `content`. The spec says a text
    serialization SHOULD accompany it for older clients; ChatGPT reads
    `structuredContent`. Keep the no-duplication decision, but revisit if a
    non-ChatGPT client is targeted.

## Priority 4 — operations and scale (read)

12. **Session lifetime is the main reliability limit.** V2 deliberately stores no
    password (the legacy stored Fernet-encrypted passwords and re-logged in).
    When ManageBac's session cookie ends, the Approved host deletes the account
    and the student must reconnect. → Measure the real cookie lifetime in the
    test host (log issue/expiry times, not values) before deciding anything; if
    it is short, consider an explicit, opt-in, revocable credential vault rather
    than a silent default.
13. **Approved host per-call cost.** `call_authenticated` scans every cached
    account and reads the store for each one on every tool call (O(accounts)
    SQLite reads per call). → Evict with a TTL/LRU (e.g. idle 30 min, max 200
    sessions) and check only the calling account.
14. **Blocking I/O on the event loop.** Report export (`ReportWriter.save`) and
    SQLite access run synchronously inside async handlers. Negligible at one
    user; → move to `anyio.to_thread.run_sync` before multi-user testing.
15. **Evidence retention.** The report writer stops at 1,000 runs (121 used) and
    then silently stops collecting on the host (it logs to stderr only). → Surface
    "reports disabled: limit reached" in the workbench and host health endpoint;
    keep the no-deletion rule.
16. **Scale envelope.** A single Mac LaunchAgent + Cloudflare tunnel + SQLite +
    in-memory sessions is appropriate for a handful of students. It needs a GUI
    login after reboot and cannot run two instances (sessions are in memory).
    Moving beyond ~20 active users or needing restart-safe sessions means: a
    system LaunchDaemon or container on a server, session state in the encrypted
    store only, and structured logs (tool, duration, error code, request id —
    never content) exported with OpenTelemetry, which the new spec documents for
    `_meta` trace propagation.

## Security posture (read)

Strong: school-origin allow-list (`*.managebac.com|cn`, HTTPS, port 443, no
userinfo); no redirect following on page reads; path allow-list per route;
2 MB page cap; strict UTF-8; login-form detection; CSRF + Origin checks on the
local workbench; loopback-only workbench; encrypted OAuth/cookie state; school
text treated as untrusted in tool descriptions and server instructions.
Weak: signed URLs in outputs (item 3); encryption key stored beside the
database (documented; a Keychain-held key would raise the bar); DCR-only
registration (item 10); no outbound rate limit (item 5).

## Fixed in this pass (tested)

- `get_classes` pagination now uses the shared `listing_url`/`next_page`, so
  numbered pages without a Next link fail instead of completing early.
- Task and grade cards with an inner `[data-task-id]` are one record
  (shared `pages.outermost`, identity-based); inner IDs must match the link.
  Files use the same helper (previously Tag equality, which compares markup).
- Timetable merged cells: a class spanning periods is one slot with
  `period`..`period_end`; notes spanning days/periods keep alignment; spans past
  the last period or extra cells are errors.
- `Test Reports/Synthetic Examples/README.md` marks the 15 Sep examples as
  superseded (they fail current schemas); 24 Sep examples are current.
- 237 tests pass (10 new; 5 of them fail on the pre-fix code).

Not live-verified: all of the above, and every tool other than get_classes,
get_tasks and get_task on the pre-change MYP classes.
