# Progress

2026-09-25: Compact class-file output and local folder browser implemented in Working. Browser-compatible page headers and explicit HTTP 422 error; no fresh live Files verification yet. Fixed observed task resource icons/duplicate downloads and neutral document-preview labels; saved Biology page replayed successfully. Safe target IDs added to private reports. 124 Python tests and two Node DOM-contract tests pass. September 24 live audit: 18 class lists (four errors), 58 task details (three errors); source-layout investigation still pending. See docs/CLASS_FILES_REBUILD.md. Approved/public unchanged.

2026-09-17: Compact task presentation implemented between extraction and MCP: Markdown instructions, local media/table references, separate teacher resources/submission files, explicit submission-box evidence. History and absent-section boilerplate omitted. 101 tests pass. See docs/COMPACT_TASK_OUTPUT.md. Local preview updated; Approved/public unchanged.

2026-09-17: Rebuilt task-detail adapter after reviewing GitHub multi-user c41363d. Detail parsing is now separate from list parsing, with bounded title/section recognition, preserved editor siblings and reduced resource duplication. 85 tests pass; fresh live validation pending. See docs/TASK_DETAIL_REBUILD.md. Approved/public deployments unchanged.

2026-09-15: Task summaries, single-task detail and class-file retrieval implemented in Working with shared bounded HTML/rich-content helpers, account-scoped dispatch and opt-in exact JSON reports. 74 automated tests pass, including synthetic fixtures and MCP framing. Review: docs/TASKS_AND_FILES_REVIEW.md. Examples: Test Reports/Synthetic Examples. Live task/file validation blocked by lack of a usable authenticated session; this is NOT evidence of rejected credentials. Approved snapshots, public launch and production remain unchanged. Next: live source-to-JSON comparison before approval. This supersedes the old "Task list and one task: Not started" row below.

2026-09-13: get_classes implemented separately from login; explicit invocation in local inspector, account-scoped temporary cookie reuse, bounded pagination/cursors, shared developer reports off by default. 42 tests pass including MCP memory transport. Historical class-page parser check passed. Fresh live class retrieval and user approval pending; no Approved snapshot or production changes. See docs/GET_CLASSES.md.

Latest: user requested login-only architecture. Removed active portal.py/class retrieval and checks.py registry. New auth.py, school_discovery.py and transport.py separate responsibilities. Profile-based verification has 21 passing automated tests and awaits fresh live validation. See docs/LOGIN_ONLY.md. Earlier approved snapshot retained as history only.

2026-09-08 update: user approved login and class checking. Source-only snapshot: Approved/01-login-classes. Removed unfinished task/comment checks; explicit registry now runs only classes and exposes extracted records in the temporary session inspector. 21 automated tests pass. See docs/APPROVED_SNAPSHOTS.md. This supersedes earlier statements below that unimplemented comments block class-only readiness. OAuth remains disabled.

Master journey and review coverage: [FLOW_CHECKLIST.md](FLOW_CHECKLIST.md). Includes school discovery through notifications, unknown modules, recovery and context validation. All new flow reviews remain Unmapped until evidence is collected.

| Milestone | Status | Evidence / next action |
|---|---|---|
| Create independent Desktop workspace | Complete | README.md and historical design references |
| Adopt live-first exploration | Recorded | README.md supersedes earlier fixture-first sequencing |
| Login/onboarding rebuild | In progress | Local workbench, no invite/domain fields, live email discovery and branding verified; 18 tests pass. User-entered live sign-in next. Readiness and OAuth incomplete; docs/LOGIN_REBUILD.md |
| Live class discovery | After login | Inspect authoritative list and pagination, then verify compact output |
| Task list and one task | Not started | Follow class discovery |
| Remaining portal capabilities | Not started | Enumerate based on actual student navigation |

No production changes or live portal requests were made while creating this workspace.

2026-09-08: User moved onboarding to the first milestone. Live public school discovery was tested; local V2 implementation added and tested. No production data or deployment changes. Local preview: http://127.0.0.1:8765 on Atlas. This preview is not a ChatGPT-connectable service. Current safety gate intentionally remains closed until comment/empty-state checks and OAuth integration are implemented and verified.
# Class JSON simplification

get_classes now retrieves the entire class list in one call. Success is classes
only; no exposed cursor or duplicate text. Count/completeness checks stay internal.
Failure returns an error only, never an incomplete list. Preview and disk exports
share the exact plain payload; MCP framing is isolated in tools/server.py.
Existing report files and Approved snapshots remain unchanged.
# 25 September 2026 — legacy capability migration

Working catalogue expanded from four to twelve read-only tools. Added units,
selected unit detail, journals, discussions, current timetable, consolidated
deadlines, scoped task search and conservative source-assessment retrieval.
Added a catalogue-driven local workbench and exact synthetic response exports.
Login/page User-Agent is consistent; an account-profile check distinguishes a
page login redirect from a still-authenticated session. No Approved/public changes.

See [migration report](docs/LEGACY_TOOL_MIGRATION.md) for scope, code locations,
legacy replacements and unresolved live verification. New tools are synthetic-
tested, not live Grade 10 verified. Existing session had already been marked
unauthenticated; local preview was restarted to load the new catalogue.
# Independent review fixes — 25 September 2026

Fixed normal ungraded task handling, MCP error framing, twelve-tool model
orientation, timetable notes/colspan handling, explicit schemas and per-tool
limits. Added safe search class_ids diagnostics and shared class HTML transport.
Regression tests distinguish ordinary missing data from unsupported markup.
Working only; no Approved/public changes. Live Grade 10 checks still need login.
