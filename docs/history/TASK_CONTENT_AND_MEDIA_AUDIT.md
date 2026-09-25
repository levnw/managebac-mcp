# Task content and media audit

2026-09-17. Working only. This distinguishes implemented extraction from proposed media delivery.

## Evidence, not assumptions

Inspected the user's saved Task Details HTML without executing its attached scripts. Description location: `.core-task-show .core-task-details .show-more`; editor body: `.fix-body-margins.redactor-styles.fr-view.fr-element`. Task title: `.core-task-show > .fusion-card-item .title`, a div, not an h1/h2. Sidebar history lives in `#sidebar_info`, outside main.

Observed description: three text paragraphs and a PNG image of the chemistry worksheet, followed by blank paragraphs. The source description has no HTML table. The full document also contains cookie-policy HTML tables, which must never be mistaken for task content. Other page regions include unit information, a discussions preview, account/navigation controls and modals. They are not the task description.

The saved HTML rewrites the image source to a local saved-page companion file. Offline parsing verifies the image node and order, not a usable live download URL. Do not publish that locally rewritten path as an authenticated live image endpoint. The attached PNG was visually inspected in the preceding review. It has no source alt text; inferred image/table text must remain separate from literal source extraction.

## Old project parity audit

Reviewed GitHub `multi-user` at `c41363d325a65e652740491a8083619f41546f03`: [scraper.py](https://github.com/levnw/managebac-mcp/blob/c41363d325a65e652740491a8083619f41546f03/managebac_mcp/scraper.py), `parse_task_detail` and `fetch_task_detail`.

| Old behavior | New handling / deliberate difference |
|---|---|
| First suitable heading title | Observed task-card title preferred; historical selectors supported; ambiguity fails |
| Description heading then editor sibling | Observed structural container plus bounded historical adapters |
| HTML-to-Markdown | Ordered semantic JSON preserving rich content; compact Markdown rendering remains a presentation option |
| Embedded images with absolute URLs | Image nodes and deduplicated asset refs, preserving order and alt text when supplied |
| `fr-file` and `data-name` attachments | File references and source file-size labels |
| External anchor links | Label/destination relationships; no automatic fetch |
| Bare URL detection | Added ordered link references for plain-text URLs, excluding code/anchors |
| Resource groups with author/date/title/files | Separate grouped resources; metadata removed from duplicated content |
| Submission filename/download/upload time | Submission content retained only inside recognized submission section; no global `tr.file` scan |
| Feedback preview token | Valid URL marked as preview; opaque token not exposed or called a download |
| Sidebar creation/reminder/update history | Observed sidebar Task History section retained as source content, not guessed dates |
| Automatically fetch discussions | Explicitly not replicated; belongs to a separate retrieval operation |
| Page theme for widget | Not model content; no theme extraction needed for this tool |
| Detail cache | Not replicated; account-scoped session and opt-in reports remain separate from caching |

Not every old behavior was reliable: its generic heading fallback could choose a class title, and its heading-only Description search would also miss this div-based page. Replication means useful information coverage, not preserving those bugs.

## Content coverage matrix

| Content type | Capture/presentation strategy | Status |
|---|---|---|
| Text, headings, lists, emphasis, code | Ordered semantic nodes; compact text rendering may be added separately | Implemented, synthetic tests |
| Actual HTML table | Rows/cells/header/span relationships, not flattened prose | Implemented, synthetic tests |
| Image / image of table | Ordered image reference; deliver original pixels separately when requested | Extraction verified against attached HTML; media delivery not implemented |
| Links / bare URLs | Label/text and destination; no implicit external page reading | Implemented |
| File attachment | Reference, name, source size where available; not file contents | Implemented for supported markup |
| Video/audio/embed | Source references and type; no invented transcript | Implemented basic nodes; host playback/analysis not verified |
| Math/SVG/canvas | Preserve available labels/text with explicit uncertainty | Not equivalent to full rendered visual understanding |
| Script-rendered interactive content | Never execute arbitrary attached scripts; need dedicated evidence-backed adapter or safe rendered capture | Not implemented |
| Unknown rich elements | Preserve children and signal unsupported flattening | Implemented; not universal fidelity |

## MCP / ChatGPT media research

Sources fetched 2026-09-17:

- [MCP tool results](https://modelcontextprotocol.io/specification/2025-06-18/server/tools): structuredContent is JSON; content supports image blocks with base64 bytes and MIME type, resource links and embedded resources. Protocol support does not prove every client handles every type identically.
- [OpenAI tool-result reference](https://developers.openai.com/plugins/reference): content and structuredContent are model-visible; `_meta` is component-only. It also documents optional file upload/library/download helpers and tool file inputs. File input schemas describe ChatGPT-to-tool transfer, not automatic tool-to-model ingestion of any URL.
- [OpenAI UI guide](https://developers.openai.com/plugins/build/chatgpt-ui): widget `imageIds` can provide recognized image file IDs on later turns. IDs must come from documented upload/library/file-parameter/tool-reference flows; never invent an OpenAI file ID from a ManageBac ID.
- [OpenAI MCP server guide](https://developers.openai.com/plugins/build/mcp-server): server-side validation, authorization and bounds/rate controls remain necessary.

No universal numeric image/file-count limit per ChatGPT MCP tool result was established in these pages. That is an UNKNOWN, not evidence of unlimited processing. Unrelated REST Files API upload/storage quotas, ChatGPT manual-upload quotas or skill-import limits must not be presented as MCP attachment limits.

## Proposed delivery policy (not implemented)

1. Task lists/bulk details carry text and media references, not automatic binary downloads. This is retrieval scope, not a platform count restriction.
2. An explicit selected-media operation returns the requested originals using a client-verified mechanism: MCP image content is the candidate for images; arbitrary files need tested resource/file handling or explicit extraction.
3. Preserve original image pixels for diagrams/table screenshots. OCR is optional derived content, labelled with its source and method; never replace the original with an unverified transcription or silently fill blank worksheet cells.
4. Do not impose a guessed "15 tasks" or fixed attachment-count limit. Let a selected set proceed if it fits the verified client/transport constraints and configurable byte/time/memory budget. Budget values must come from testing and be called service limits, not OpenAI limits.
5. If only part can be delivered, explicitly identify delivered/deferred refs and a continuation/next action. Say whether media was not requested, exceeded a budget, is unsupported or failed; never call an omission a successful read. These operational media states differ from the removed task-total developer warning.
6. Reauthorize every media reference in the signed-in account. Reject arbitrary fetch URLs, validate MIME and byte bounds, control redirects, and never forward ManageBac cookies to third-party hosts. Do not turn private assets into public static links.
7. Validate real ChatGPT consumption using the user's attached worksheet and a supported document. A widget display/download alone does not prove model access.

Current `get_task` remains a one-page reference-only tool. No attachment/OCR tool, cross-class batch tool, new paid API call or arbitrary hard count limit was introduced in this review. Existing HTML/JSON/time/asset guards remain service safety limits pending measured media-specific design.

## Verification

90 tests pass. Added a sanitized observed-layout regression, sidebar history coverage, bare-link and file-size tests. Also ran the actual attached HTML through the parser and verified the exact title, all three paragraphs and ordered image reference. This is saved-page verification, not a new live fetch or ChatGPT multimodal end-to-end validation. Public Approved deployment remains unchanged.
