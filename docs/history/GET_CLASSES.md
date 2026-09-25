# get_classes — 2026-09-13 implementation

Status: implemented and automated-tested; not yet approved by user or tested against a new live authenticated class list. Production and Approved/01-login-classes remain unchanged.

## Boundaries

- sources/managebac/classes.py fetches and parses ONLY /student/classes/my. Main-list tiles only, no sidebar/browse-other-classes records. Actual next links are validated for same school, exact route and page-only query. No redirects, password handling, class detail or other capabilities.
- tools/classes.py defines get_classes, strict input/output schemas, MCP annotations/result, deduplication, completeness and continuation. All callers use this same implementation.
- tools/server.py registers the tool with the installed MCP 1.x low-level server using an injected authenticated caller. The memory-transport protocol test verifies listing and calling. This is not a public OAuth/MCP endpoint and does not connect ChatGPT yet.
- tools/session.py holds cookies and bounded cursors per authenticated browser session in memory. Authentication itself remains in onboarding/auth.py. Login NEVER invokes class retrieval. Passwords are not saved. No tool silently logs in again.
- diagnostics.py is a shared opt-in context used by discovery/login HTTP events and class retrieval/output. Server-controlled MBV2_DEVELOPER_MODE=1 enables it; unset/default is OFF.

## Interface

Input: {} for a new list, or {"cursor":"returned opaque cursor"} to continue. No arbitrary school URLs or account IDs accepted. Output includes classes[{id,name,url}], total_reported, complete, next_cursor and error. Error is null on success; partial failures carry records already validated and isError=true. Always combine continuation responses by class ID. complete=true means the full traversal count matches the source, not that this response contains all earlier pages. A snapshot is not a permanent guarantee and undetectable same-count changes remain possible.

Two portal pages per invocation; at most 50 records per source page, 300 characters per name, 20 digits per ID, 2MB downloaded HTML per page. Unexpected sizes fail visibly, not silently truncate. Traversal capped at 100 pages and 5000 unique IDs. Cursors are opaque, session-scoped, expire after ten minutes, and limited to ten per session. Replaying a cursor re-fetches its segment, with no double advancement. Expired/other-session cursors fail before network access. On failure retry the original cursor or start a fresh list as directed.

MCP result contains identical compact JSON in TextContent and structuredContent for compatibility. No academic detail, debug events, or auth secrets are included in normal tool results. Debug output is not appended to the tool result.

## Local inspection

Preview runtime update: the temporary terminal process repeatedly stopped between turns. The loopback preview is now a macOS launchctl submitted job named `com.managebac.v2.preview`, using the existing interpreter and `--app-dir /Users/server/Desktop/ManageBac-V2`. It is independent of the chat terminal; no public listener or boot/login LaunchAgent plist was installed. Inspect with `launchctl list com.managebac.v2.preview`; stop with `launchctl remove com.managebac.v2.preview`. Do not start another process on port 8765 while this job is running. Restarting clears temporary sessions, cookies, cursors and reports, but not the profile database.

Sign in on http://127.0.0.1:8765, then select Get classes. Next results is enabled only if a continuation is returned. The page displays the exact CallToolResult JSON returned by the local tool adapter, not a promise about ChatGPT's hidden context. /api/tools/get_classes is a CSRF-protected browser workbench endpoint, not itself MCP transport.

Developer mode: restart with MBV2_DEVELOPER_MODE=1 to collect reports, then use Show developer reports or GET /api/reports in the same browser. Default off collects no reports. Reports contain bounded events, page counts/status, tool schema, exact class tool result and its compact serialized byte count. No raw HTML, email, password, cookies, auth headers, CSRF tokens or signed asset URLs. Mode cannot be enabled by a remote query parameter/browser checkbox. Reports are private to the setup session; at most five retained, removed on expiry/restart/account switch. Reports are not reconstructed retroactively. Source-to-output comparison presently includes parsed page counts plus final records, not a full source HTML archive.

Cookies and cursor state remain only in server memory until setup expiry (30 minutes), account switch or server restart; a periodic reaper removes expired idle sessions. Refresh preserves an unexpired browser session. The existing SQLite database still contains only profile metadata/cooldown, no cookies or classes. Readiness orchestration remains unimplemented and disconnected from login.

## Evidence

42 automated tests pass: complete/partial pagination, identical names with different IDs, duplicate IDs, empty/unrecognized pages, session expiry, count mismatch, unsafe links, cursor isolation, debug off/on, credential exclusion from reports, web flow, and actual MCP memory transport. Historical European School page parsed 10 class tiles, reported 15, and a next link to page 2. No fresh live password or academic request made during implementation. Existing test-client deprecation warning remains; it does not fail the suite.

Dependencies use installed MCP 1.27.2 and pyproject bounds >=1.27.2,<2 rather than assuming the latest major is compatible. A dedicated locked V2 runtime and public authentication integration are still needed before deployment.

References consulted: https://modelcontextprotocol.io/specification/2025-11-25/server/tools and https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/v1.x/README.md.
# Current contract — one batch, JSON only

This section supersedes the historical implementation notes below.

Call get_classes with {}. It reads all enrolled-list pages internally, deduplicates
by ID, checks reported totals and returns only {"classes": [{"id": "…", "name": "…", "url": "…"}]}.
There is no total_reported, complete, next_cursor, error:null or duplicated text.
The preview and response.json contain this exact application payload, not an MCP
wire envelope. Failures return only {"error": {"code": "…", "message": "…"}}, never
partial classes disguised as a complete list. No cursor state or Next results UI.

Internal bounds: 100 pages, 5,000 classes, 1 MB compact JSON, 60 seconds total;
existing per-page 2 MB and 50-record bounds still apply. Limits fail explicitly,
never truncate. Count diagnostics remain in the developer report, not class data.

Only tools/server.py constructs the MCP-required envelope: content is empty and
structuredContent carries the JSON once. Errors set protocol isError=true. SDK
serialization may include its default isError=false for successful calls; that is
not a field in our class payload or saved response.json. Structured-only delivery
passes SDK in-memory tests; the eventual ChatGPT connector still needs a live test.

Old saved reports are historical evidence and have not been rewritten. Run Get
classes again after signing in to create a report in this new format.
