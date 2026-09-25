# ManageBac MCP — working backlog

Updated: 2026-09-07. Captured from Levan's notes. Order is not priority.

## Product purpose

Reduce friction between the student and the school portal. Primarily bring useful school information into ChatGPT, including teacher-assigned files, new messages, classes, and other important school information.

## Tracking convention

Statuses: Not started → Investigating → In progress → Ready to verify → Verified; Blocked when a dependency prevents progress. Record evidence and next action when updating status. GitHub issue states are reports, not proof that a feature works or is broken. Link existing issues before creating duplicates. Do not mark work verified until its user-facing result has been checked.

| ID | Item / desired result | Status | Related GitHub issues | Next action |
|---|---|---|---|---|
| MB-01 | Reliable access to teacher-assigned files, new messages, class lists, and other useful school data | Not started | #18, #35, #49 | Inventory supported data and identify gaps, especially messages and assigned files |
| MB-02 | Clear, organized, compact ChatGPT output; structured JSON where useful, bounded responses and details on demand to avoid filling the context window | Not started | #57, #12, #10, #15, #24 | Review payloads and presentation against actual student questions |
| MB-03 | Seamless, straightforward setup with minimal steps | Not started | #13, #45, #46, #47, #50 | Walk through fresh enrollment and reconnection |
| MB-04 | During signup, visibly load and verify protected school data before declaring success or handing off to ChatGPT | Not started | #13, #45, #49 | Require a successful protected-data fetch, with loading/progress and an actionable failure state |
| MB-05 | A discoverable Report a problem flow | Not started | #48 | Define entry point, report destination, and safe diagnostic context |
| MB-06 | Find the student's ManageBac school/domain quickly without copying and pasting a URL | Not started | — | Explore school lookup/autocomplete and ambiguity handling |
| MB-07 | Preserve note: “Come along with me through the butterflies and bees and doing so” | Needs clarification | — | Meaning unclear; retain verbatim until clarified, do not infer a feature |

## Existing GitHub backlog

Checked https://github.com/levnw/managebac-mcp/issues on 2026-09-07: 44 open issues. Existing reports cover widgets, formatting/schema, authentication, school-data freshness, monitoring, architecture, privacy, and future native apps. They have not all been revalidated against the deployed branch.

Relevant starting points:
- #57: section-aware task widgets / minimum useful output.
- #13: OAuth setup flow.
- #45–47: session errors, password changes, self-service account management.
- #48–49: problem visibility and detecting scraper breakage.
- #56: architecture review.

## Recent evidence / progress

- Preserved v2/code-reuse principles in V2_DESIGN_PRINCIPLES.md, with links retaining earlier detailed tables/lists. Added MODEL_CONTEXT_DEBUG_PLAN.md: fixture/live transport parity, exact outgoing payload inspection, model-vs-widget field separation, evaluation cases and official OpenAI sources. Both are planning documents; implementation not started.

- Second architecture pass: PROBLEM_REGISTER.md records 18 additional or expanded findings with stable IDs, preliminary priorities, evidence state and suggestions. Four failure behaviors reproduced offline. Includes retrieval dependencies and public research leads; no production changes. “Mass data” remains an example, not a committed feature requirement.

- Architecture/design review completed as a proposal: ARCHITECTURE_REVIEW.md. Covers failure boundaries, a private downloadable reference library, capability inventory, adaptable extraction, cost model, onboarding and migration gates. Implementation has not started; full portal capture is a proposed next design step.

- Commit c41363d deployed: detects HTTP-200 login rejection pages, adds a process-local five-minute automatic-login cooldown, and fixes class-fetch lock scope. Focused regression tests passed.
- Latest live check in this conversation: stored European School session returned HTTP 200 at /student/classes/my and parsed 15 classes; the service class-fetch operation also returned 15. Screenshot: /Users/server/Desktop/managebac-evidence/classes-response.png.
- Full current ChatGPT/Dia user-facing verification remains outstanding. The signup protected-data verification requirement (MB-04) is not complete merely because login-error handling was improved.
- Preserve all enrolled users, databases, credentials, OAuth data, and tunnel files; no deletion or rotation without explicit confirmation.
