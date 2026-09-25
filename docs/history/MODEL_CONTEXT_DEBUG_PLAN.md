# Model-context inspection and replay plan

2026-09-07. Specification only; no debug implementation, full website mirror, live capture, or production changes in this turn.

## Objective

Let Levan compare source evidence with extracted facts and the actual MCP response our server emits. Validate accuracy, completeness, relevance, output size and tool discoverability before visual polish. A plain local report/JSON export is sufficient for the first version.

## Two test modes, one implementation

Replay transport returns captured/anonymized page and endpoint responses; live transport retrieves authorized school responses. Both pass through the SAME adapters, domain validation, projection and MCP serialization. Do not replace the tool itself with canned ideal JSON: that would skip the extraction defects we want to expose.

Use a synthetic authenticated account context in offline replay, with external network disabled. Production authentication must never acquire a bypass flag for convenience. Test auth separately with success, rejection, expiration, lock, redirects and unavailable states; validate real onboarding later. Offline success cannot establish live authentication readiness.

A static full website is an aspiration, not an achievable claim from a single capture. Start with an explicit coverage manifest of page types and interaction states: class lists, paginated lists, task detail, discussions, unit lists/detail, file folders, empty states and failures. Dynamic endpoints need recorded fixtures; writes need simulated state transitions. Missing fixtures fail visibly and never fall back to live requests. Keep images/styles local for offline viewing; scrub auth material and signed URLs. Never commit raw student records.

## Inspection artifact for every run

1. Scenario/question and expected facts, expected tool choices or acceptable alternatives, and forbidden/unnecessary calls.
2. Tool catalogue snapshot: names, descriptions, input/output schemas, annotations, version/hash; MCP initialization instructions emitted by our server.
3. Incoming tool request and arguments, with correlation ID.
4. Source fixture references, retrieved paths, request count, cache state and timings.
5. Extracted domain data and validation/coverage results.
6. Exact serialized outgoing MCP result, captured after serialization at the protocol boundary. For replay with synthetic data, keep exact bytes and a hash. Live exact capture is private, opt-in and access-controlled; a scrubbed export is labelled redacted, not byte-exact.
7. Separate views for model-facing content/structuredContent, component-only result _meta, and local debug evidence. Never copy the whole capture into an ordinary ChatGPT tool response.
8. Byte count, item/field counts, duplicated material, truncation/cursor metadata; estimated token count labelled with tokenizer/model assumptions. Exact host context use is not knowable from our server alone.
9. Expected-vs-actual comparison and a diff against a reviewed baseline. Baselines need human/source review; do not bless current output just because it is repeatable.

The outgoing response and catalogue show what we provide, not ChatGPT's hidden prompt, complete internal context, host transformations or guaranteed attention to every field. Local inspection and actual ChatGPT behavioral tests are complementary.

## OpenAI documentation findings

Official pages fetched 2026-09-07; previous Apps SDK reference/testing links redirected to Plugins documentation. This naming change alone is not a reason to change packaging or deployment.

- Define tools: group coherent user actions, document inputs/outputs and permissions, distinguish reads/writes, and make descriptions explain selection boundaries. Source: https://developers.openai.com/plugins/plan/tools.
- Tool results: content and structuredContent are exposed to model and component; result _meta is component-only. Structured data should match declared outputSchema. Put essential facts, warnings and coverage in model-facing fields; widget-only fields cannot supply facts the model needs. Source: https://developers.openai.com/plugins/reference#tool-results.
- Testing: use MCP Inspector for direct calls and test actual client behavior; retain prompt/result evidence and refresh changed metadata. Source: https://developers.openai.com/plugins/deploy/connect-chatgpt.
- Metadata evaluation: test direct, indirect and negative requests and revise metadata against observed selection behavior. Source: https://developers.openai.com/plugins/guides/optimize-metadata.

Do not assume a tool description is an enforced policy or that a JSON schema proves semantic accuracy. Authorization and validation remain server responsibilities. _meta is not a safe location for passwords/tokens: the client component receives it.

## Proposed tool/context contract

Each tool describes: purpose; when to call and when not to; required IDs and where to obtain them; defaults/limits; output meaning; freshness/completeness; important failures; side effects and retry safety. Shared short guidance explains school-domain concepts, timezone policy, source-data trust, navigation through identifiers, and partial-result handling. Do not repeat a huge manual in every description or assume clients honor server instructions identically.

Example candidate description, not a registered tool:

> Retrieve the instructions, due date, status and linked attachment metadata for one task. Use when the student asks about a specific assignment. Obtain class_id and task_id from task search/list results; do not guess them. This does not download file contents or retrieve discussions. The result states freshness and missing fields. Read-only.

Keep the public tool set organized around user goals, not one tool per HTML page or internal helper. Evaluate overlapping get/show tools before deciding to merge or remove them. Preserve real capability coverage while reducing ambiguity. Selected writes remain proposals; they require distinct contracts, simulated failure/retry tests and explicit authorized live verification.

## Evaluation layers and acceptance gates

1. Extraction: fixture facts match expected IDs, dates, labels and relationships; missing pages, partial coverage and wrong weeks are detected.
2. Context: emitted schema is valid; essential context/errors remain visible; output budget enforced with continuation; no accidental HTML/secrets or unexplained truncation.
3. Selection: direct and indirect requests pick a suitable tool; unrelated/unsupported prompts do not activate inappropriate tools; ambiguous tasks produce candidates/clarification, not guessed IDs.
4. Interpretation: model answers use correct dates, cite the right source, preserve uncertainty and do not claim empty results from failed coverage.
5. Client integration: metadata discovery, transport, auth, optional UI and follow-up calls work in ChatGPT. API-based experiments can supplement this but do not prove identical ChatGPT behavior and may incur separate API costs.

Golden cases: class list without journal discovery; task instructions without discussions; teacher feedback vs class messages; file metadata vs document reading; old task pagination; wrong timetable week; one failed class in a batch; no available journal vs empty journal; expired login; malicious instructions embedded in school content; duplicate/ambiguous titles; write requested without a clear destination. School content is untrusted data, never instruction authority.

Prioritize deterministic replay tests on every relevant change; use a small model/client evaluation set when tool descriptions or contracts change. Do not require paid inference for every parser fixture. Measure actual client behavior before choosing numerical token/latency budgets.

## First deliverable when implementation begins

A local replay runner producing source/expected/extracted/outgoing-response files plus a readable diff for one classes fixture and one task fixture. No elaborate UI. Verify that a deliberate extraction error appears in the report. Then expand coverage and add model tool-selection evaluations. Full reference capture and v2 implementation remain tracked work, not completed by this plan.
# Developer-mode requirement update — 2026-09-13

User requires shared diagnostics across implemented components, OFF by default, with reports requested when developer mode is enabled. Essential failures/completeness remain visible in normal responses. See [DEVELOPER_MODE.md](DEVELOPER_MODE.md). This is recorded design direction, not completed implementation.
