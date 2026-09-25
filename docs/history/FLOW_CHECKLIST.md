# ManageBac V2 — user-flow review checklist

Created 2026-09-07. Master journey checklist; design and discovery before implementation. Live-first. Order follows the student journey, not a commitment to implement every item sequentially.

Statuses: Unmapped → Observed → Specified → Built → Verified. Use Blocked with a reason when necessary. A checked review item means evidence recorded, not necessarily code implemented. Current status: all flows Unmapped in v2. Prior v1 class access is useful evidence but does not verify v2.

## 00. Map the real portal

- [ ] Capture the authenticated home page and expanded navigation available to the student.
- [ ] Inventory actual sections, submenus, tabs and school/programme-specific modules.
- [ ] Separate available-but-empty, unavailable-to-role, disabled-at-school, unsupported-by-us, and unknown.
- [ ] Build a private page/state catalogue: screenshot, sanitized structure, observed route, page purpose, capture time and permission context.
- [ ] Include pagination, dialogs, folders and representative empty/error states; do not claim a complete snapshot from one page.
- [ ] Confirm which navigations change read state or perform actions before exploring them.
- [ ] Link each flow below to evidence and expand this list when new features appear.

Output: portal map and coverage manifest. This can proceed alongside school discovery design and precedes claims of full feature coverage.

## 01. Find your school

Desired journey: enter school name → choose verified school → confirm identity → continue.

- [ ] Investigate school-name autocomplete/search as the primary route instead of mandatory URL copying.
- [ ] Establish where verified school/domain mappings can come from; inspect official school-finding behavior and public directory options before choosing implementation.
- [ ] Evaluate existing known schools and optional email-domain hints. An email domain is not proof of a ManageBac domain.
- [ ] Handle schools with similar names, campuses, alternate spellings and multiple portal domains.
- [ ] Confirm school name/logo and verified hostname before collecting credentials.
- [ ] Retain manual school URL as fallback; normalize and validate it safely.
- [ ] Handle school not found, unavailable portal and wrong selection with an easy return step.
- [ ] Remember the selected school where appropriate so reconnection does not repeat discovery.

Unknown: exact reusable official discovery mechanism and whether its use is supported. No working automatic finder claimed yet.

## 02. Authenticate and verify readiness

Desired journey: sign in → visible access checks → ready, limited access, or actionable recovery.

- [ ] Map password, SSO and 2FA paths actually offered by the school.
- [ ] Separate app OAuth authorization from ManageBac account/session authentication.
- [ ] Avoid redundant standalone enrollment followed by another identical sign-in where the client flow permits continuity.
- [ ] Verify protected account access and a minimum data contract before displaying success.
- [ ] Treat explicit empty class data as potentially legitimate, not an automatic login failure.
- [ ] Display real progress milestones; optional checks must not indefinitely delay readiness.
- [ ] Distinguish wrong school, rejected sign-in, temporary lock, expired session, permission denial, page change and service outage.
- [ ] Centralize session/cookie ownership and bounded retry behavior across enrollment, reads and background work.
- [ ] Preserve useful account state during recovery; never advise password changes from an ambiguous response alone.

## 03. Connect to ChatGPT and make the first request

- [ ] Provide a clear continuation from verified account readiness into the connector flow.
- [ ] Verify discovery, authorization, tool catalogue, metadata refresh and actual tool calls.
- [ ] Expose understandable current capabilities and limitations without a giant instruction manual.
- [ ] Test first questions, follow-ups, ambiguous requests and unrelated requests.
- [ ] Show usable reconnection/support guidance when transport works but school access fails.

## 04. Browse classes

- [ ] Retrieve authoritative class rows, IDs, names and source links.
- [ ] Verify pagination, current/archived terms and duplicate navigation links.
- [ ] Retrieve classes only; journal availability belongs to journal discovery.
- [ ] Define compact response, completeness and continuation.
- [ ] Test school-specific labels and empty results.

## 05. Find and list assignments

- [ ] Inspect task list filters: class, term, status, type, dates and pagination actually supported.
- [ ] Search returns contextual candidates when names are ambiguous.
- [ ] Keep listing/search independent of full task detail and discussions.
- [ ] Preserve partial search coverage and explain failed classes.
- [ ] Ensure old tasks remain reachable through explicit continuation/search.

## 06. Understand one assignment

- [ ] Retrieve instructions, due date/time, status, source and attachment metadata.
- [ ] Preserve teacher links, relevant rubric/assessment context and unit relationships when available.
- [ ] Distinguish missing fields from retrieval failure.
- [ ] Offer feedback/discussions/unit expansion explicitly, without hidden required fetches.
- [ ] Verify model-facing payload against the real page before styling it.

## 07. Find and read learning materials

- [ ] Map files in tasks, class folders, unit resources, discussions/messages and portfolios as distinct sources.
- [ ] Preserve original class/folder/context breadcrumbs.
- [ ] Handle pagination, folder traversal and partial failures.
- [ ] Separate file metadata lookup from downloading and reading content.
- [ ] Verify selected PDF/document/image/text behavior; label unsupported formats and unreadable scans.
- [ ] Bound bytes, extraction work and model context; return sections and source references on demand.
- [ ] Keep attachment authorization and caches account-scoped; handle expired links.
- [ ] Inspect external document links as a separate access boundary.

## 08. View feedback, grades and reports

- [ ] Distinguish task feedback, rubric scores, derived statistics and official report grades.
- [ ] Inspect comments, released reports and school/programme grading conventions.
- [ ] Confirm explicit no-grades-yet states in the new year; later cover populated examples.
- [ ] Do not present calculated averages as official school grades.
- [ ] Preserve failed-class warnings in both text and widgets.

## 09. Explore units and curriculum

- [ ] List unit summaries without fetching every popup.
- [ ] Retrieve selected unit detail and its tasks/resources separately.
- [ ] Verify actual programme fields and distinguish missing vs inapplicable concepts.
- [ ] Keep identifiers and relationships usable in follow-up calls.

## 10. Plan time: timetable, calendar, deadlines

- [ ] Map timetable, assessment deadlines and non-assessment events separately.
- [ ] Verify requested date/week is actually returned; no silent wrong-week fallback.
- [ ] Establish account/school timezone and user display timezone explicitly.
- [ ] Handle weekends, holidays, date ranges, historical/future weeks and empty schedules.
- [ ] Preserve student-specific event assignment and access rules.
- [ ] Review calendar export/subscription only as an optional later capability, not a current commitment.

## 11. Read messages, discussions and announcements

- [ ] Identify class, task, year-group and other actual communication locations.
- [ ] Distinguish message content from notifications about that content.
- [ ] Inspect threading, attachments, authors, timestamps and pagination.
- [ ] Determine whether opening a message marks it read; label this side effect accurately.
- [ ] Keep read-only viewing separate from reply/send actions.

## 12. Review notifications and changes

- [ ] Inspect the notification centre and how notifications link to source records.
- [ ] Determine read/unread/dismiss behavior before testing actions.
- [ ] Distinguish notification entries from actual changes in task/grade data.
- [ ] Evaluate “what changed since last check?” with a clear baseline and coverage.
- [ ] Avoid automatic background polling/push infrastructure unless its value and cost justify it.
- [ ] Preserve links to the underlying task/message rather than return disconnected alerts.

## 13. Journals, portfolios and other available modules

- [ ] Journal discovery owns availability checks; classes remain independent.
- [ ] Map reflections, evidence, attachments and teacher responses where available.
- [ ] Inspect possible CAS, EE, TOK, personal project, service-learning, attendance or other modules only if present for this account/role.
- [ ] Record absent/unknown modules rather than promise them as supported.
- [ ] Verify educational distinctions such as reflection count vs evidence count.

## 14. Selected writes — later, separately evaluated

- [ ] Prioritize user-valued actions after corresponding read flows work.
- [ ] Candidates: submit a file/link, reply to a discussion, add a reflection; not all are committed scope.
- [ ] Verify destination, authority, required fields and consequences.
- [ ] Model uncertain outcomes and retries without duplicate writes.
- [ ] Check resulting state before claiming success and invalidate dependent caches.
- [ ] Simulate first; perform live writes only with explicit task authorization.

## 15. Recovery, account management and Report a problem

- [ ] Recover from expired sessions without restarting school discovery unnecessarily.
- [ ] Handle changed passwords, revoked client authorization and suspended accounts distinctly.
- [ ] Preserve last-known information with explicit age/coverage when appropriate.
- [ ] Report a problem includes a correlation ID and sanitized diagnostic context.
- [ ] Give actionable status and clear escalation without exposing credentials or full private payloads.
- [ ] Design account update/export/deletion deliberately; no destructive test on current users.

## Cross-cutting checklist for every flow

- [ ] User goal and minimal required retrieval documented.
- [ ] Source evidence, fields, permissions and side effects identified.
- [ ] Narrow capability plus explicit optional enrichment.
- [ ] Typed result with completeness, freshness, timezone and provenance where relevant.
- [ ] Exact outgoing MCP payload inspectable privately; model-facing vs widget-only data separated.
- [ ] Bounded requests, output size, pagination and account-scoped cache behavior.
- [ ] Empty, partial, expired, denied, unavailable and changed-page cases tested.
- [ ] Clear descriptions/parameters tested for selection and follow-ups.
- [ ] Presentation preserves critical warnings and needs no mandatory network decoration.
- [ ] Verified portal result, service result and actual ChatGPT experience tracked separately.

## Immediate next work

Two paired discovery tasks: inspect school-finding options for Flow 01, and capture the current authenticated navigation for Flow 00. Then implement the first narrow live class slice (Flow 04), with the login/session boundary kept explicit. No snapshot collector, finder or capability is implemented merely by this checklist.
