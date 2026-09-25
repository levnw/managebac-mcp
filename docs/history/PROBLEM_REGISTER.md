# ManageBac MCP — growing problem register

Reviewed 2026-09-07 against c41363d. Design/diagnosis only; no implementation in this pass. Source findings describe code behavior, not proof every user has experienced it. Reproduced means exercised offline with mocked network/cache responses, not against a live student. Earlier architectural findings remain in ARCHITECTURE_REVIEW.md.

## Additional findings

| ID | Priority | Finding and evidence | State | Suggested direction |
|---|---|---|---|---|
| PR-01 | High | Task detail always requests discussions; failure of the second request prevents returning the successfully fetched task. scraper.py:1179 | Source-confirmed | Task core and discussion capability separately retrievable; explicit expansion when desired |
| PR-02 | Medium | Unit list fetches every unit popup and merges all detail; one exception aborts the operation. scraper.py:1655 | Source-confirmed | List summaries first; unit detail by ID; partial outcomes for requested expansions |
| PR-03 | Medium | show_tasks and show_files fetch the entire class list for display names; a name lookup failure can turn successful primary retrieval into a failed widget. server.py:2500 onward | Source-confirmed | Render from primary result; use already-known labels or fall back to class ID; decoration must not become an availability dependency |
| PR-04 | Medium | Task widget enrichment fetches a task list and all classes; broad catch silently drops enrichment. server.py:2111 | Source-confirmed | Pure rendering projection; explicit cheap optional enrichment with known provenance |
| PR-05 | High | Date-specific timetable probes four parameter names; if none matches, returns first available week and caches it under requested anchor. scraper.py:492 | Reproduced offline | Cache only validated date coverage; expose requested vs returned range and unavailable state |
| PR-06 | High | tag_search skips failed classes and reports a count without disclosing missing coverage. scraper.py:737 | Reproduced offline | Count means matches in searched coverage; return failed class IDs and partial status |
| PR-07 | High | Grades retrieval includes fetch_errors, but _grades_widget_sc drops them. server.py:2085 | Reproduced offline | Presentation must preserve completeness, freshness and errors from the underlying result |
| PR-08 | High | Generic _batch uses gather without per-item error handling; one failure raises instead of returning successful siblings. server.py:1644 | Reproduced offline | Consistent keyed per-item outcomes; distinguish whole-operation auth failure from item failures |
| PR-09 | High | _now_info, file datetime conversion and relative-day logic use host timezone; server instructions claim dates are school-local. scraper.py:437,450; server.py:48,1788 | Source-confirmed | Explicit school/account timezone; define display timezone separately; do not assume container timezone equals school timezone |
| PR-10 | Medium | find_task scans task lists sequentially across all classes and automatically opens a fuzzy winner's detail/discussions. scraper.py:1985 | Source-confirmed | Search returns ranked candidates with class/date/context and coverage; fetch chosen detail separately; prefer scoped queries |
| PR-11 | High | Common error path returns an error object but does not set CallToolResult.isError; early error paths sometimes do. server.py:2666–2694 | Source-confirmed | One consistent typed error/result policy across normal, widget and batch paths |
| PR-12 | Medium | Multi-class file widget replaces each original folder path with class label. server.py show_files batch branch | Source-confirmed | Preserve class and folder as different fields; compose breadcrumb at render time |
| PR-13 | Medium | get_tasks truncates at 12 and inserts a note object into the task array; show_tasks uses a different projection. server.py:1653,2500 | Source-confirmed | Pagination metadata outside entity arrays; defined consistent coverage and explicit display filtering |
| PR-14 | Medium | refresh invalidates every cached response for the current user even for a question about one task. server.py refresh branch; cache.py:clear_user | Source-confirmed; expands earlier cache finding | Resource-scoped invalidation and freshness requests; reserve whole-account refresh for an explicit need |
| PR-15 | High | Upload helper calls HTTP 200/201/204 success without checking the uploaded asset appears; no cache invalidation afterward. scraper.py:1832–1982 | Source-confirmed; CLI path, not advertised MCP | Before exposing writes: verify resulting asset/submission, reconcile unknown outcomes, invalidate dependent views |
| PR-16 | Medium | Health/activity request counters query the same globally capped 500-row log, so total_requests and requests_today are retained-window counts. cache.py:log_request,admin_health_stats | Source-confirmed | Separate bounded diagnostics from aggregate counters; label metrics accurately |
| PR-17 | Medium | Only classes have a fetch lock; simultaneous identical task/detail/file misses can each start retrieval. cache get/fetch/set patterns | Source-confirmed | Per-account/resource request deduplication; retain bounded upstream concurrency |
| PR-18 | Medium | Journal capability description tells callers to depend on has_journal in get_classes; journal fetch itself has separate heuristics for absence. server.py:1416; scraper.py:1456 | Source-confirmed; expands earlier journal coupling | Journal capability owns discovery; distinguish unsupported, empty, denied and unrecognized; class list remains independent |

## PR-19 — Batch task retrieval can overwhelm model context

Added 2026-09-08 at the user's request. Priority: High. State: Design risk to address; not a newly reproduced defect. No implementation authorized.

Required design scenarios include selected tasks from one class, all tasks from one class, selected tasks across two or more classes, and all tasks across those classes. Narrow tools must still support deliberate composition; separating capabilities must not prohibit useful batches. This does not commit to a whole-account mass-data feature.

Risks: excessive model-facing output, repeated class metadata, unbounded task descriptions or attachments, one class consuming the entire result budget, and silently omitted tasks being mistaken for complete coverage. Large batches can also amplify upstream requests and latency. JSON alone does not solve these problems.

Proposed safeguards to evaluate before implementation:

- Explicit class/task scope and filters; distinguish listing task summaries from retrieving selected task details.
- Bound the entire response, not only each class separately: item limits and serialized output size budgets, with token estimates where useful.
- Cursor-based continuation with per-class coverage and item failures preserved; distinguish more available results from failed retrieval.
- Keep completeness, omissions, and continuation metadata outside task arrays. Never claim "all" if results are partial or truncated.
- Retain task ID and class ID for unambiguous follow-up; avoid repeating large class objects and fetching unrelated discussions or attachments.
- Separate data retrieved or cached internally from data sent to the model. Preserve essential facts and warnings when projecting compact output.
- Test sparse and populated classes, uneven class sizes, long task text, multiple pages, and partial batch failures. Inspect the exact outgoing payload and its size.

Related: PR-08 batch failure isolation, PR-13 truncation and response consistency, PR-17 request deduplication. Exact limits, schema, and batch interface remain undecided.

## PR-20–23 — References, content fidelity, and actionable errors

Added 2026-09-08 following user discussion and a read-only inspection of the local legacy source. No live portal verification or implementation in this pass.

| ID | Priority | Finding / design risk | Suggested direction |
|---|---|---|---|
| PR-20 | High | Existing cache stores JSON by user and operation key; tasks already have IDs and detail lookup. This is not a unified entity-reference contract. Title-only summaries cannot reliably identify duplicate titles or support later detail retrieval. | Compact summaries with stable source IDs and parent context; detail retrieval by reference, not fuzzy title matching. Account/school/type/parent scope internally; IDs are not authorization. Cache expiry must not make a valid source ID unusable. |
| PR-21 | High | parse_tasks filters tags using a broad rejection regex and a 40-character cap; task type scans the entire row for Summative/Formative. Legitimate labels may be omitted or classification influenced by unrelated text. Source-confirmed rules; current live impact unverified. | Identify actual tag/type/status elements from evidence; retain source labels, separate criteria from tags and assessment type where supported; distinguish empty from extraction failure. |
| PR-22 | High | Rich-text converter has no explicit table handling, drops relative hyperlink destinations, and omits embedded file links on the assumption widgets render them. Task detail separately extracts some assets, but resource extraction recognizes selected URL patterns and skips resource groups with no matching files. Submitted files scan all tr.file rows rather than an explicitly scoped submission container. Source-confirmed; affected live examples still needed. | Preserve meaningful text structure and in-place asset references; classify inline images, embedded files, external links, teacher resources, student submissions and feedback separately. Do not assume all missing output is absent source content. |
| PR-23 | High | Need a consistent error contract across summaries, details, assets and batches, extending PR-06–08 and PR-11. | Stable error codes, plain-language explanation, affected scope, retry guidance and safe diagnostic ID. Preserve successful siblings; distinguish expired session, denied access, missing resource, changed layout, rate limiting, expired download link and unsupported extraction. Never turn failure into an empty success. |

### Proposed summary-to-detail contract (not implemented)

- List returns compact entity summaries with IDs. A subsequent detail call resolves the selected ID in the authenticated account and validates access. Titles are labels, never primary keys.
- Default summary fields depend on the entity and question: task ID/title/class reference; deadline/status for scheduling queries; tags when relevant. Compact must not mean stripping the facts required to answer correctly.
- Apply the same pattern to classes, files, calendar events and discussions after confirming their source identities. Where a stable source ID is absent, design a server-side opaque reference with explicit lifetime/recovery rules, not a fabricated permanent ID.
- Consider SQLite entity/reference records plus validated JSON payloads and freshness metadata; do not create a duplicate whole-portal database by default. Model-facing output is a separate bounded projection, not a dump of storage tables.
- Class, task and asset identities must remain account scoped. Signed download URLs and feedback tokens are not durable identifiers and should not be copied into ordinary model-facing records or logs.
- An asset reference means the asset exists, not that its contents were read. Detail responses must make unread images/files and failed extraction apparent. Fetch image/file content on demand with size limits; do not silently discard an image that contains the assignment instructions.
- Preserve text/image order, lists, tables, equations where supported, links and asset relationships. Deduplicate payloads without deleting meaningful repeated placement. Treat external page/file content as untrusted data, not instructions.
- Errors must distinguish valid empty data, unrequested detail, more available results, partial failure and unreadable content. Do not call credentials incorrect merely because a session redirected to login.

Evidence pointers (legacy local source): managebac_mcp/cache.py:29–96; managebac_mcp/scraper.py:32–125, 541–667, 898–1083. Suggested tests: duplicate task titles, stale cache references, cross-account IDs, numeric/long tags, tables, relative links, image-only instructions, mixed resource posts, expiring URLs and per-asset failures. These are test requirements, not claims of reproduced live defects.

## Offline evidence from this pass

- Requested timetable 2026-09-07; all four mock responses described 2026-08-03. Returned August days with no error and called cache.set. This exercises scraper behavior; downstream date filtering can turn the wrong week into empty output rather than fixing provenance.
- Tag search over two classes with one failed task fetch returned count=1 without fetch_errors/error.
- Grades projection receiving fetch_errors omitted that field in structured widget content.
- Generic batch containing one valid result and one raised error raised for the overall batch.
- No live login, grade mutation, message read, submission, or production deployment was performed.

## Retrieval dependency map

Cold paths; actual network count can be lower with cache hits, higher with pagination/retries. C=class count, U=unit count.

| User operation | Current underlying work | Proposed responsibility boundary |
|---|---|---|
| List classes | Class list + C class pages for journal flags | List classes only; follow class pagination when needed |
| Get one task | Task page + discussions page | Task core; discussions optional/separate |
| Show one task | Above + class task list + class listing (and its cold journal checks) | Render supplied task; no required network lookup for decoration |
| List units | Unit list + U unit popups | Unit summaries; expand selected unit |
| Search tasks by title | Classes + sequential task list per class + winning detail/discussions | Scoped candidate search; explicit detail retrieval |
| Get grades for one known class | All classes for names + that class tasks | Known-class grades without unrelated class dependency |
| Show files | File traversal + classes for labels | Requested files; labels/folders preserved without mandatory extra fetch |
| Retrieve a requested week | Up to four URL parameter guesses | Observed/validated route variant and date-range assertion |

“Only retrieve classes” means no unrelated capability discovery. It does not require exactly one HTTP request: class pagination, authentication and identity validation may be necessary. A useful field already present on a fetched page can be extracted without an extra request. Explicit aggregate operations can compose narrow capabilities with budgets; a mass-data feature is not an accepted requirement.

## What would make future architectural judgments stronger

Maintain four linked references:
1. Portal capability map: real school objects, their relationships, roles/modules, and where each appears. Distinguish task attachments, class files, discussion attachments, unit resources and portfolio media; do not collapse them into one folder concept.
2. Retrieval ledger: tool → service → page requests, cache keys, extra enrichments, latency/request budget, and side effects. Capture cold/warm cases and error behavior.
3. Evidence catalogue: sanitized page/state snapshots + expected extracted entities + pagination/completeness checks. Include screenshots and structured response samples. Link each extraction rule to evidence, not developer recollection.
4. User-intent matrix: representative questions, required data, optional enrichment, bounded response and recovery path. Example: “What did the teacher say?” should identify whether the answer comes from task feedback, class discussion or another message source.

The portal's internal architecture is not publicly known from this code. An authorized snapshot can establish observable behavior, not its backend database schema. Start with one representative student account and mark other schools/programmes unverified. Avoid broad crawling or reading messages just to complete a diagram; those actions may change read state.

## Public research signals, not committed features

Research checked 2026-09-07. Public reviews are self-selected, may concern older versions, and do not establish prevalence or our current bug rate.

- A recent student discussion reports excessive navigation to grades and confusion about CAS evidence vs reflection counts. Design implication: direct answers with correct educational meaning, not just shorter navigation. Source: https://www.reddit.com/r/IBO/comments/1tylg8d/what_annoys_you_most_about_managebac_or_toddle/.
- App Store feedback includes difficulty locating assignments/grades. Treat as interview prompts, not a representative survey. Source: https://apps.apple.com/us/app/managebac/id1437382327?platform=iphone&see-all=reviews.
- ManageBac's class documentation describes discussions, attached media/files, folders, and student-specific events/deadlines. Implication: events are not necessarily assessment tasks, and access/assignment scope must be retained. Source: https://help.managebac.com/hc/en-us/articles/360019106671-Adding-Class-Discussions-Files-Events.
- Official mobile guidance describes resources in portfolios, classes and unit streams. “Find my teacher's file” therefore needs source coverage and provenance, not just a class Files tab. Source: https://help.managebac.com/hc/en-us/articles/51163845282457-ManageBac-iOS-Android-app-mobile-QuickStart-Guide.

Candidate questions for design validation: “What changed since I last checked?”, “Where is the file the teacher mentioned?”, “Which deadlines are assessments versus other events?”, “What feedback have I received?”, and “Did my submission actually arrive?” These are suggestions, not newly authorized implementation scope.

## PR-24 — Missing concise domain orientation

Added 2026-09-08 at the user's request. State: V2 design requirement; not a claim that the legacy server contains no instructions. A model needs a compact explanation of ManageBac's entity relationships, including class-scoped journals and the distinction between tasks, units, resources, submissions and feedback. Tool names alone may not teach this reliably.

Maintain a short canonical orientation alongside accurate tool descriptions, without repeating a manual in every result or advertising unimplemented features. Qualify school-specific availability and verify that the client actually receives the intended guidance. Draft and acceptance criteria: [MODEL_ORIENTATION.md](MODEL_ORIENTATION.md).

## Next investigation priority

Prioritize wrong answers and hidden incompleteness (PR-05–09, PR-11) before performance cleanup. Then isolate presentation from fetching and define list/detail boundaries. Capture a bounded reference set to test proposed contracts before refactoring. High/Medium here are preliminary product-risk judgments, not exploit severity scores. All findings remain open until explicitly addressed and verified.
