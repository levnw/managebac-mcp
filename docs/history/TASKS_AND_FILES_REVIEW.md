# Task and class-file retrieval — review draft

Updated 2026-09-15. Implemented in **Working**, not promoted to Approved or deployed.

## Verdict

The new retrieval pipeline passes 74 automated tests, including the existing login/classes suite, new synthetic task/file fixtures and an in-memory MCP client/server round trip. It is a reviewable implementation, **not yet a live-validated scraper**.

Stored sessions redirected to login. A single scoped sign-in attempt did not establish a usable session; its cause was not determined. This does not establish that the password was rejected. No further password attempts were made. No private live task/file HTML was captured. Current markup assumptions therefore need comparison against authenticated ManageBac pages before approval.

## Tool boundaries

| Tool | Arguments | Requests and output | Deliberately excluded |
|---|---|---|---|
| `get_classes` | none | Existing enrolled-class list implementation, unchanged | Tasks, files, journals |
| `get_tasks` | `class_id` | All supported list pages in that class; compact task summaries | Opening individual tasks, attachments or discussions |
| `get_task` | `class_id`, `task_id` | Exactly one task page; rich instructions and sections actually present | Extra tabs, discussions, downloads, other tasks |
| `get_class_files` | `class_id`, optional `folder_id`, `recursive=false` | All pages in the selected directory; optional explicit descendant traversal | Task attachments, submissions, file contents |

IDs are numeric **strings from ManageBac**, not array positions. Task identity includes its parent class. File IDs are included when the page supplies a valid native ID. Asset `ref` values are URL-and-kind hashes local to the returned asset catalogue, not persistent database IDs. A signed URL changing can change its reference. Folder records preserve parent relationships.

## Captured information

### Task summaries

2026-09-17 update: At the user's request, missing source-total observations are now developer-only diagnostic events, not task-list payload fields or model-facing schema/description warnings. Success returns class_id, url and tasks only. Pagination and available-total consistency checks are unchanged; this presentation change does not establish independent completeness. Older reports retain their original output.

2026-09-17: The response also includes a top-level `url` pointing to the first task-list page actually retrieved for the selected class. Individual `tasks[].url` links still open individual tasks. This link is returned even for a verified empty list, with no extra request. Previously saved reports remain historical and are not rewritten.

Each record contains `id`, `title`, `url`, and only source-present metadata: due-date text/machine datetime, status, assessment type, tags, and explicitly labelled details. No invented timezone, year, teacher or grading interpretation. Summaries do not include full instructions or fetch detail pages.

### Individual task

Identity and metadata accompany an ordered `description` tree. Text, headings, paragraphs, emphasis (including common editor CSS), ordered/nested lists, quotes, tables and cell spans, code blocks, line breaks, images/alt text, captions, links and file links are preserved structurally. Image `srcset` variants are retained. An `assets` array avoids repeating URLs throughout the tree.

Separate fields hold teacher `resources`, student `submissions`, `feedback`, `assessment`, and `history`, when those sections appear in the downloaded page. Group author/title/posting text is retained when recognized. Feedback viewer URLs are labelled previews, not downloadable documents. Opaque preview values are not exposed as URLs.

`state: not_on_page` means the parser did not find that section on this page—not that no information exists elsewhere. `discussions: {state: not_requested}` explicitly records the boundary. Present empty content is distinct from a missing section. Missing required instructions or ambiguous sections fail rather than masquerade as a complete task.

Images, PDFs, documents, external links, videos and embedded viewers are **references, not extracted file contents**. Embedded media and mathematical/visual content carry review warnings. This implementation does not OCR images, transcribe video or parse binary attachments. A future explicit asset-reading tool should own those costs and access checks.

### Class Files

File records include a reference, name, containing folder, optional native ID, byte size (including zero), source timestamps, content type, uploader, tags and ordered descriptions when supplied. Folder IDs, names, URLs and parents remain separate. The default call lists child folders without opening them. `recursive=true` is an explicit cost/scope choice.

Metadata supports ordinary and multiply JSON-encoded `data-ec3-info` values without destructively removing backslashes. Malformed metadata is an error, not a silently discarded file.

## Architecture

```text
Authenticated host / local authenticated API
  -> tools/session.py          account-scoped cookies, lock, optional export
  -> tools/catalogue.py        one registration and dispatch list
  -> tools/tasks.py | task.py | class_files.py
       -> tools/retrieval.py   argument, time and output bounds; safe errors
       -> sources/managebac/pages.py       bounded read-only HTML requests
       -> sources/managebac/tasks.py       task list/detail parsing only
       -> sources/managebac/files.py       directory/file parsing only
       -> sources/managebac/rich_text.py   semantic content and asset catalogue
  -> plain JSON payload
       -> tools/server.py     MCP protocol framing
       -> diagnostics.py      developer-only response.json + report.json
```

New extraction code was written independently. Existing classes established the separation and error/report conventions. Historical scraper routes/selectors informed fixture design; its implementation was not copied or imported. Shared transport and rich-content handling prevent task and file tools from each owning divergent HTML/security logic.

Login still performs no task/file retrieval. The Working local API adds authenticated catalogue and tool-dispatch endpoints; it does not add a public unauthenticated tool route. Existing classes-only MCP hosts remain classes-only unless explicitly supplied the new name-aware authenticated callback. The Approved test launch imports its approved snapshot, not Working, so these tools are not available on the public test connector yet. No widget or new visual interface was built.

## Exact model output and developer reports

The tool payload has one JSON representation. MCP places it in `structuredContent`, with an empty `content` array; no duplicate text rendition is generated. The required transport envelope is not copied into `response.json`. Failure responses contain only `error` with a safe code/message. Success does not add `error:null`, `is_error:false` or other generic success flags.

Developer mode is off by default. When enabled, the session's existing report writer exports that same payload to a private run directory. It is a diagnostic export, **not a cache or permanent student-data store**. Cookies remain account-scoped and do not enter reports. Export failure is logged safely and does not invalidate successful retrieval. Reports have 0700 directories and 0600 files, a 2 MB/run and 1,000-run cap; no automatic evidence deletion.

Live output could contain academic information and signed resource URLs that grant temporary access. Treat it as private; do not publish reports, commit them, or serve their folder through Cloudflare. Resource URLs are intentionally preserved for use, so the response must not be described as free of all access-bearing links. Authentication passwords/cookies/OAuth tokens are not passed into reports.

Open **Working/Test Reports/Synthetic Examples/** for four generated runs: task list, task detail, class root files, recursive files. These contain fictional fixture data, not the student's account. Open each `response.json` for exactly the model-facing payload; `report.json` holds separate safe diagnostic events.

To regenerate locally from Working, using an environment with the project dependencies:

```sh
python scripts/replay_tools.py
python -m pytest -q
```

The replay command uses an HTTP mock through the real session/tool/parser/report path. It cannot access the live network or perform login. Each run creates new dated evidence, not another copy of source code.

## Safety, cost and failure behavior

- Only same-school, scoped HTML GETs. Redirects are not followed; authentication remains separate. Asset URLs are returned but never fetched.
- Per new call: 60 seconds, 250 KB serialized JSON, up to 50 listing pages and 1,000 entries. Each HTML page is capped at 2 MB. Task detail makes one request.
- Rich content has additional nesting, node, text and asset limits. These are hard failures, not silent truncation. The whole-call output limit may be reached before those individual limits.
- Pagination validates destination, loops, changing lists and task counts when available. A later-page failure returns an error rather than a partial successful list.
- Missing task totals generate a warning. File aggregate totals are not considered trustworthy yet, so file results explicitly warn that pagination was followed but the source total was not independently verified.
- 401/login redirect, 403, 404, 429, upstream failures, unsupported HTML, identity conflicts and size limits remain distinguishable. No generic "credentials rejected" label is inferred from an arbitrary failure.
- Source text is untrusted content, not instructions to the model. Scripts and form controls are not included or executed.

## Tests and evidence

74 tests passed with the existing project Python environment. One unrelated Starlette/httpx deprecation warning remains. New tests cover compact lists, pagination, task identity, section separation, rich semantics/assets, recursive/nonrecursive folders, nested metadata encoding, empty/missing/error differences, redirects, authorization failures, context/page bounds, cookie isolation, opt-in exact report writing, catalogue registration and MCP payload/error framing. Tests use synthetic HTML and do not demonstrate compatibility with every ManageBac account or programme.

## Critical gaps before approval

1. **Live selector validation is mandatory.** Capture representative authenticated pages privately: populated and empty task lists, multi-page results, several task types, file root/folders, feedback and submissions. Compare visible source against every resulting field. Do not rely solely on tests whose fixtures reflect the parser's own assumptions.
2. JavaScript-only content, alternative programme layouts, new pagination labels, folder UI variants and embedded viewers are not established. Unsupported layouts should fail visibly; add sanitized fixtures after observation.
3. Math is retained as available text/labels with a warning, not guaranteed mathematical equivalence. `<picture>` sources beyond the image's own `srcset`, unusual editor styles and complex media need further coverage.
4. Some resource title/author text occurs both in structural content and extracted metadata. It preserves context but is not maximally compact. Refine against real markup before dropping anything.
5. Output schemas define top-level contracts but nested records are currently broad objects. Strengthen nested schema descriptions/contracts after real page validation; current tests check key semantic relationships but cannot prove exhaustive field correctness.
6. Large task lists currently fail at the budget rather than offering date filters or cursor continuation. Do not tell users to use a filter that does not exist. Decide a bounded selection contract based on actual usage; no cross-class bulk tool is included.
7. No persistent academic cache, binary file reader, discussion fetcher, write tool, widget, or public deployment is included. Those must not be implied by these read-only tools.

Next approval gate: authenticate once through the normal login flow, capture representative live evidence, reconcile parser assumptions and schemas, then review exact JSON with the user. Only after approval should the verified modules move into an approved snapshot and the authenticated test host be updated.
