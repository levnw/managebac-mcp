# ManageBac MCP: architecture review and proposed design

Date: 2026-09-07. Reviewed source: c41363d. Status: proposal, not implementation.
Scope: student-accessible ManageBac workflows, ChatGPT as primary consumer, low operating cost, reliable onboarding, and a private design/testing reference. This is a targeted source review, not an exhaustive security audit or a completed cross-school capability inventory.

## Judgment

Follow-up: see PROBLEM_REGISTER.md for the deeper retrieval audit, 18 tracked findings, four offline reproductions, public research signals and the proposed evidence/capability mapping method.

The current implementation is a useful prototype with several sound foundations, but it lacks reliable boundaries between obtaining a response, proving authentication, extracting data, establishing completeness, and presenting an answer. Its weakness is not Python, SQLite, or a single service. It is that uncertainty is frequently discarded between these steps. More widgets and generic AI browsing would magnify that weakness.

Keep request-scoped user identity, encrypted credential storage, hashed OAuth tokens, pure parsing functions, and per-user structured response caching. Do not assume all isolation is complete: the separate attachment cache is keyed by URL alone. Build explicit contracts and observable state before broadening feature coverage.

## Source-backed findings

| Finding | Evidence | Consequence / recommended decision |
|---|---|---|
| Signup success is weaker than data readiness | http_server.py:200–251 calls login and then starts prewarm as a background task | Verify a protected page and minimum capability before success; report optional capability failures separately |
| Authentication remains heuristic | auth.py:64–126 rejects known forms/paths; authed_get mainly checks login URL and 401 | Classify responses before parsing, require positive evidence for session readiness; distinguish locked, expired, forbidden, unavailable, and changed page |
| Recent cooldown is mitigation, not complete session ownership | auth.py stores failures/locks in process memory; direct login does not consult cooldown; enrollment calls login directly | One account-session coordinator must govern all callers; failure state must survive restarts if retry policy relies on it |
| Cookie persistence loses metadata | auth.py converts cookies to dict; users.py:226–239 stores name/value JSON | Preserve domain/path/expiry/secure metadata and define rotation/version ownership; do not treat cookie existence as proof of login |
| Partial files can look complete | scraper.py:1308–1363 breaks on request exceptions and caches accumulated results; page cap is not exposed | Return coverage, continuation and failure information; never label incomplete extraction as a complete empty collection |
| Class parsing relies partly on navigation | scraper.py:195–227 collects matching links across the whole page; fetch_classes fetches one list page | Separate authoritative list rows from navigation; verify pagination and expected totals |
| Class listing does unrelated work | fetch_classes fetches every class page for has_journal | Make journal capability lazy; ordinary listing should not require one extra request per class |
| Enrollment eagerly fetches unused data | prewarm fetches classes, timetable, upcoming and every class task list | Small readiness check, then demand-driven retrieval; background work needs outcomes, budgets and deduplication |
| Schemas are mostly envelopes | server.py:1565–1585 uses a result property without typed contents or an arbitrary-object schema | Define real domain/result contracts and validate them before returning data |
| Rendering and protocol handling are coupled | server.py is 2,721 lines with inline/loaded widget HTML, transformations, diagnostics and dispatch; scraper.py is 2,014 lines | Split by responsibility within one codebase; file size alone is not the defect |
| Important file functionality does not reach MCP | server instructions route attachments to widget selection; file-reading/submission helpers appear in scraper/CLI but not current MCP tool registry | Audit feature accessibility from the actual ChatGPT tool surface, not helper-function existence |
| Separate file cache is not tenant-scoped | scraper.py:1692 onward hashes URL alone and can return cached bytes before current-account authorization | Tenant/permission-bound attachment handles before exposing this path to multiple users; not a demonstrated production exploit |
| File size cap is checked after download | fetch_file_bytes reads r.content before enforcing maximum | Bound streamed download and extraction budgets if this path is used |
| Diagnostics duplicate sensitive content | cache.py log_request stores full args/responses, retains latest 500 globally | Structured redacted events, correlation IDs and optional private diagnostic captures; exclude signed links/credentials from logs |
| Regression evidence is thin | parser tests skip missing fixtures; earlier suite skipped 19; save_fixtures uses fixed student IDs and no user context | Representative sanitized fixtures and explicit coverage gates; mock auth tests do not establish real login correctness |

## Product scope: what “every feature” should mean

Target everything that the connected student's role can access, incrementally verified by school/programme/module. Do not promise teacher/admin capabilities to a student or assume every school enables the same modules.

Create a capability matrix: domain, operation, permission, source, sample page/state, adapter version, read/write classification, completeness, test evidence and supported schools. Initial domains: classes; tasks/deadlines; task instructions/feedback/discussions; assigned and submitted files; grades/reports; timetable/calendar; messages/announcements; units; portfolios/CAS and other enabled modules. These are inventory targets, not a claim that all are currently available.

Distinguish absent, permission-denied, unsupported, temporarily-unavailable and unrecognized. Writes need separate workflows: validate destination, preview the effect, use an operation identifier to prevent duplicate retries, and verify the resulting state. No blind retry of an uncertain submission.

## Downloadable snapshot: a private reference library, not a full portal clone

For each representative page and interaction state, capture screenshot, sanitized DOM, semantic labels, observed request/response shapes, entry route, pagination, permissions, timestamp, school/programme variant, expected entities and completeness assertions. Capture drawers, tabs, attachment lists and pagination states rather than only top-level pages. A screenshot explains appearance; DOM and network evidence explain behavior.

Proposed bundle:

    managebac-reference/
      index.html               # searchable local page/workflow catalogue
      manifest.json            # capture scope, time, variants, limitations
      capabilities.json        # feature coverage and evidence
      workflows/               # navigation steps and state transitions
      pages/                   # sanitized DOM, screenshots, semantic maps
      network/                 # scrubbed response samples, no auth material
      fixtures/                # synthetic/anonymized regression examples

Keep raw authenticated captures private and short-lived; reusable fixtures must be scrubbed before repository inclusion. Remove cookies, authentication headers, password fields, CSRF values and signed download URLs; retain structure and synthetic IDs. Redaction must also cover screenshots. Block live network and state-changing forms/scripts in an offline replay. Do not recursively crawl all links: viewing messages may mark them read, and attachments may lead to external systems. Begin with a bounded set of representative student workflows and record unknowns.

Playwright traces provide screenshots, DOM snapshots and network inspection; HAR replay can help reproduce recorded requests. Neither captures an entire server application or every unvisited state. Sources: https://playwright.dev/docs/trace-viewer and https://playwright.dev/docs/mock.

## Adaptability without paying for an AI browser on every request

Prefer school-authorized public API access where available and adequate. ManageBac's official guidance says tokens are administrator-managed; ordinary student onboarding cannot assume them. Endpoint coverage must be verified. Source: https://help.managebac.com/hc/en-us/articles/360018226931-Enabling-ManageBac-Public-API-for-Integrations.

Fallback order: supported API → verified authorized web-response adapter → semantic DOM extraction → bounded browser diagnostics. Internal JSON endpoints can reduce presentation coupling but are still undocumented dependencies. Semantic roles, labels, headings, identifiers and relationships usually make better anchors than CSS position. They still require validation. Source on semantic locators: https://playwright.dev/docs/locators.

For unknown page variants, record the failed contract, gather a private bounded diagnostic snapshot, and ask a model/operator to propose an adapter change. Validate against old/new fixtures and perform a controlled read-only canary before publishing the adapter. Reuse validated structure across compatible variants; never share user content or authorization. Do not let an LLM silently reinterpret grades, dates or submission targets in production.

No approach can guarantee understanding of arbitrary future UI, auth or permission changes. The feasible goal is to survive cosmetic changes, detect semantic changes promptly, degrade honestly, and repair adapters cheaply.

## Recommended architecture: modular monolith

Keep one deployable application initially, with explicit boundaries:

    ChatGPT / widgets
           |
    MCP interface + bounded response projections
           |
    Capability services + typed school-data model
           |
    Retrieval coordinator + freshness + completeness policy
           |
    Versioned ManageBac adapters
           |
    Account-session coordinator + HTTP transport
           |
    ManageBac

SQLite stores account state, normalized records/cache metadata and durable work status. A separately bounded worker handles expensive extraction/optional refresh when justified. The reference library validates adapters outside the ordinary request path. Do not start by introducing microservices, a vector database, a permanent browser per user, or per-request model reasoning.

Every result should distinguish success/partial/unavailable and include observed_at, source_updated_at when actually available, stale status, coverage, continuation and recoverable errors. Do not invent a source modification time from the fetch time. Use real typed Class, Task, Attachment, Message and Grade objects; model-specific compact views and widgets consume those objects rather than duplicate extraction logic.

For content, return summaries and identifiers first; retrieve requested detail or file sections by handle. JSON is useful structure but not a token budget. Bound item count, field projection and serialized size; disclose truncation and offer a cursor. Do not return a complete document merely because it fits a 40,000-character cap.

## Seamless onboarding and recovery

Find school → authenticate → visibly check protected access → verify minimum data contract → ready for ChatGPT. Fetching zero classes is not inherently invalid; an authenticated explicit empty state must be distinguished from failed extraction. Optional capabilities may be pending or unavailable without invalidating an otherwise usable connection.

Prefer one connector-driven authorization journey; standalone enrollment should resume into it without unnecessarily repeating credential entry. School search should use a verified directory/observed domains with a manual fallback; an email domain is a hint, never proof of school mapping.

On expiry, try one coordinated refresh; if unsuccessful, show reconnection required and preserve account/data state. Report a problem should attach a diagnostic identifier and sanitized operation/status context, not the student's complete tool response. Success must refer to a verified milestone, not a completed background task dispatch.

## Cost design and measurement

Main drivers: active accounts × cache misses × upstream pages per question, downloaded bytes, extraction CPU, browser time, model diagnostics, and operator repair time. User count alone cannot establish a monthly price or a database migration threshold.

Current cold prewarm costs approximately 2C+3 page fetches for C classes before redirects/retries: 1 class listing, C journal checks, C task lists, timetable, upcoming. At C=15 that is about 33 requests. It is code-path arithmetic, not a measured average. A minimal class-readiness check can avoid most of that upfront work; capabilities still load later when requested.

Illustrative demand model: 1,000 daily active users × 5 questions × 20% misses × 3 upstream requests/miss = 3,000 upstream requests/day. At 30 requests/miss it becomes 30,000. These are assumptions, not cost estimates or tested capacity. Measure bytes and latency before selecting a host. Separate ChatGPT-side context cost/latency from operator-paid API inference; tool payload size does not by itself imply an operator model API charge.

Use lazy retrieval, per-user single-flight requests, incremental refresh where supported, bounded per-school/host concurrency, request budgets, explicit stale reads, file extraction caching within authorization boundaries, and no idle-account polling by default. A shared schema-change investigation is cheaper than rediscovering the same change for every user. SQLite remains plausible until measured contention, workload, availability or operational requirements justify migration.

## Design process before implementation

1. Inventory student journeys and current GitHub issues; label reports as reproduced, outdated, duplicate or unverified. Build the capability matrix.
2. Define and collect the bounded private reference library, including empty/expired/forbidden/partial states. Keep account interactions controlled.
3. Write domain/result contracts, session/readiness states, error taxonomy and response budgets.
4. Compare adapter strategies on identical fixtures: extraction accuracy, completeness detection, request count, latency and adaptation effort.
5. Design three complete journeys: first connection, read a teacher-assigned file, recover from expiry. Include loading, partial results and support handoff.
6. Only then choose migration slices. Preserve working functionality and replace one capability at a time behind stable interfaces.

Decision gates: no false enrollment success in failure fixtures; no silent partial result; demonstrated tenant isolation; explicit unsupported states; bounded output; pagination checks; measured warm/cold latency and upstream requests; no duplicate writes under uncertain retry; representative sanitized fixtures actually run. Numeric latency/cost targets should be agreed after a baseline, not invented as guarantees.

## Outstanding uncertainties

School API availability and detailed coverage; SSO/2FA behavior; messages/read-state effects; cross-school/programme variations; present ChatGPT file-selection behavior; production load, bandwidth, restore capability, and monthly budget. Latest evidence of 15 classes proves that account/path worked at that time, not full portal coverage or durable reliability. No production behavior changed during this review.
