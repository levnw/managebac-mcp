# Class Files browser and task follow-up

2026-09-25 (Asia/Tbilisi). Implemented in Working only. Not promoted to Approved or deployed to the public connector.

## What is built

`get_class_files` reads the Files section of one class. The default is the selected directory, with its list pagination followed internally. A returned folder ID can be opened separately. `recursive: true` deliberately requests all discovered descendant folders; this is not the default.

The local inspector now displays clickable folders, parent/root navigation, file names and source links, size and uploader when available, plus an explicit recursive checkbox. It still shows/downloads the exact JSON. It does not upload, delete, edit, execute, or automatically download the listed files. File links open the original URL in a new tab rather than embedding arbitrary documents in the authenticated preview.

Examples of tool inputs:

```json
{"class_id":"10"}
```
```json
{"class_id":"10","folder_id":"701"}
```
```json
{"class_id":"10","recursive":true}
```

These are fixture IDs, not the user's live class IDs.

## Architecture and code locations

All paths here are relative to `/Users/server/Desktop/ManageBac-V2/Working/`:

| File | Responsibility |
|---|---|
| `sources/managebac/files.py` | Decode bounded file metadata, extract file rows/folder links, distinguish explicit empty pages from unknown layouts. |
| `sources/managebac/pages.py` | Same-school bounded HTML GETs, browser-compatible headers, status/redirect handling, pagination validation. |
| `tools/class_files.py` | Arguments/schema, directory scope, page/folder traversal, duplicate/conflict/loop limits. |
| `tools/file_output.py` | Compact file records and direct download links; reuses the existing rich-content renderer, not task fetching. |
| `tools/task_output.py` | Existing rich-content rendering also used for file descriptions; task presentation remains separate from file retrieval. |
| `onboarding/static/file-browser.js` | Local JSON-driven folder/file view; no independent scraper, HTML injection, file proxy or content cache. |
| `onboarding/app.py` | Serves the added static script; existing authenticated tool dispatch is unchanged. |
| `tools/session.py` | Account-scoped invocation and private reports; now logs only whitelisted numeric target IDs alongside diagnostics. |
| `tests/test_class_files_v2.py` | File contracts, HTTP handling, schema, recursion, framing and diagnostic regression tests. |
| `tests/test_file_browser.cjs` | Lightweight DOM-contract checks for navigation, safe links and stale-result clearing. |

No school-page logic belongs in login. No Files request triggers task retrieval or auto-login. No new external dependency, paid API, persistent academic cache or duplicate application tree was introduced.

## Compact response contract

Top level: `class_id`, `url` (the selected Files page), `recursive`, `files`, `folders`; `folder_id` only for a selected non-root folder.

Each file has `name` and direct `url`, with source-provided `id`, `size_bytes` or `size_display`, `content_type`, `updated_at`, `uploaded_by`, `tags`, and compact Markdown `description` when available. Rich descriptions can have accompanying `media` and `tables`. Root files omit null `folder_id`; descendant files retain their parent folder ID. No invented ID is created when a native ID cannot be established.

Each folder has `id`, `name`, `url`, and `parent_id` for non-root parents. Folder relationships remain explicit for recursive output. A listed folder is not necessarily read unless recursion was requested or that folder was opened separately.

No global `assets` lookup, opaque file ref indirection, DOM trees, creation dates, null placeholders, or pagination warning arrays are exported. The output schema rejects unknown file/folder properties. Operational total-availability notes stay in `report.json`. Empty files/folders arrays represent a recognized listing, not a failed request.

File links are references, not read contents. They can expire, and source permissions still apply. ManageBac file IDs are not OpenAI file IDs. This remains a Files browser/listing tool, not a binary-reading tool.

## What the old project taught us

Reviewed local `managebac-mcp/managebac_mcp/scraper.py` (`parse_files`, folder discovery, recursive traversal, byte/text readers) and `auth.py`. Remote `multi-user` still resolved to `c41363d325a65e652740491a8083619f41546f03` during this work.

- Preserve both metadata-backed rows and table-style file rows, including pages containing both. The old implementation's fallback could miss mixed layouts.
- Preserve filenames, byte sizes, uploader labels, folder relationships, and private download URLs. Decode actual JSON layers; do not globally replace backslashes or silently skip malformed rows.
- Do not silently break traversal on an upstream error and return accumulated results as complete. Working returns an error without a partial list.
- Do not automatically crawl every folder for a root-list request. Recursion is explicit and bounded.
- The old client documents reduced Files markup for non-browser user agents. Validated page GETs now use its browser-style UA, an HTML Accept header and same-school Origin/Referer. Redirects remain unfollowed and no cookies are sent to external media by this tool.
- The September 17 Files failure report actually contains HTTP **422**. Previously this became generic `upstream_unavailable`; it now becomes `upstream_rejected` with a precise explanation. Header compatibility is an evidence-informed change, **not proof the live 422 is fixed**.

## Verification and limits

- 124 Python tests pass; one existing Starlette/httpx deprecation warning.
- Two Node DOM-contract tests pass; JavaScript syntax checks pass.
- MCP in-memory transport verifies class-file `structuredContent` equals the plain payload without duplicate text.
- Root pagination, selected empty folder, explicit recursive folder relationships, cycle rejection, partial upstream failure, mixed row layouts, zero-byte files, malformed metadata, conflicting IDs, HTTPS download addresses and closed schemas are covered.
- Service budgets remain 50 pages, 1,000 entries, 250 KB JSON and 60 seconds per call. HTML is bounded to 2 MB per page. These are service safeguards, not OpenAI file-upload limits.
- Synthetic examples were regenerated through the real ToolSession/report pipeline under `Working/Test Reports/Synthetic Examples/20260924T224231...`. Their UTC date is September 24; local date is September 25. They are not live school results.
- No fresh authenticated Files response has been validated in this turn. A real Files page, preferably including a folder and a PDF, is still needed. Browser DOM-contract tests do not replace visual end-to-end testing in the user's browser.

## Task issues: fixed versus still open

Fixed based on the user's actual saved Biology page:

1. Remove observed resource-header/file-type icons from resource rows, not arbitrary instructional images.
2. Remove an icon-only duplicate download control only when its exact URL already has a named file link in that row. Unique links survive.
3. Generic PDF previews are now `previews`, labeled `Document preview`, not `feedback_previews` or `Teacher feedback preview`.
4. Future error reports retain safe numeric class/task/folder identifiers, so failed requests do not have to be reconstructed from sequence order.

Actual saved-page replay: `Working/Test Reports/Saved Page Replays/20260924T224249628930Z-get_task-002b26df5967/response.json`. All three teacher PDFs remain, each with one file media reference. Explicit empty submissions and enabled upload control remain. This is a replay, not a new live request. Original reports were not overwritten.

Still open from the September 24 live audit:

| Failure | Target |
|---|---|
| Unrecognized description | Spanish `48874628`, U1/L3: Los Tipos de celebraciones |
| Unrecognized description | Physics `48907042`, Quiz |
| Unrecognized description | Physics `48932225`, The Discovery of Subatomic Particles |
| Unrecognized task list/empty state | Spanish Grade 8 class `<class id>` |
| Unrecognized task list/empty state | Biology class `<class id>` |
| Unrecognized task list/empty state | Mathematics class `<class id>` |
| Unrecognized task list/empty state | Wellbeing class `<class id>` |

The run covered 18 classes: 14 lists succeeded, four failed; 58 listed task details were attempted, 55 succeeded and three failed. Failed class assignments were reconstructed from the sequential audit order. Unknown task lists must not become empty lists by assumption. No speculative selector/empty-state changes were made. The 21 `submission.box=not_detected` results also remain unverified, not evidence of closed submissions. Clearer submission field names remain a review decision.

## OpenAI files and the Google Drive comparison

Official documentation checked September 25:

- [Plugin reference — File APIs](https://developers.openai.com/plugins/reference#file-apis): optional upload/select/download helpers and tool file inputs. It mentions tool-returned file references, but does not establish that an arbitrary ManageBac URL or ID is automatically readable by the model. File input metadata is not an output-delivery contract.
- [MCP connectors](https://developers.openai.com/api/docs/guides/tools-connectors-mcp): Google Drive exposes discovery/search and a separate `fetch` for contents. This is useful public interface evidence, not access to its private implementation or proof of identical ChatGPT plugin internals.
- [MCP tools](https://modelcontextprotocol.io/specification/2025-06-18/server/tools): image content and resource links are distinct protocol results; host support and actual model receipt must be tested.

Recommended next layer: an account-authorized selected-file operation shared by class files and task attachments, separate from discovery. Resolve a known asset within its class/task context; never trust an arbitrary model-provided URL. Recheck source access and signed URLs, bound bytes/time, isolate cookies across hosts/redirects, verify MIME and explicitly report unavailable/unsupported content. Preserve original images; do not substitute guessed OCR for diagrams or scanned tables. No background bulk indexing or upload of academic files is required for this architecture.

Native file/image delivery is **not yet implemented or verified in ChatGPT**. We did not install Google Drive, send school files to a new service, or invent an OpenAI attachment count limit. Confirm the exact supported output mechanism and perform a real connector test before claiming the model sees PDF/image contents.

## How to try it

In the updated local Working preview, sign in → Get classes → choose a class → Get class files. Click a returned folder to open it, or explicitly select Include all descendant folders. The JSON below the browser and developer response exports use the same tool payload.

After the local restart, sign in again. A loopback URL on another computer requires the existing SSH forward. The public approved connector still exposes classes only. Next review: validate real Files output, investigate the seven task failures from their source pages, then agree the file-content delivery contract before approval or deployment.

Runtime verification: the existing `com.managebac.v2.preview` LaunchAgent automatically restarted the preview as PID 94876 after the old process stopped. The served `/file-browser.js` is the new browser and `/api/bootstrap` confirms developer mode is on. A redundant manual start could not bind the occupied port and exited; no second listener remains. This runtime fact supersedes older notes that the preview lacked a persistent job. No launch configuration was edited.
