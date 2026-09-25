# V2 principles preserved from the design conversation

2026-09-07. Durable record of the conversation's recommendations and user requirements, not a claim that v2 is implemented. Faithful consolidation, not a verbatim transcript. Preserve the detailed tables and lists in ARCHITECTURE_REVIEW.md and PROBLEM_REGISTER.md rather than replacing them with this summary.

## Core judgments

- More concerning than wasted requests are cases where information becomes misleading. Prioritize wrong weeks, silent missing search coverage, discarded error details, timezone assumptions and false success before cosmetic cleanup.
- An operation retrieves what it promises. Classes do not discover journals; journal retrieval owns that capability. Pagination and authentication are necessary work, not redundancy. Extracting useful data already on a page can be cheap; fetching unrelated pages is a separate decision.
- Small capabilities should compose into deliberate broader answers with budgets and partial outcomes. “Mass data” was an example, not a committed feature.
- Fresh architecture, selective reuse, gradual replacement. Keep the current service available while v2 develops. Avoid a big-bang cutover.
- Two major parts: access/capabilities and presentation, joined by shared typed data contracts. This does not require three services.
- Presentation consumes results and must preserve completeness, freshness, provenance and errors. Display labels must not become mandatory network dependencies.
- Define connected, complete, empty, stale, unavailable, unsupported, denied and partial explicitly. A successful HTTP response is not evidence of successful login, accurate extraction or completed submission.
- Keep a modular monolith initially. Additional frameworks, services, browser instances and databases need measured justification.
- Ordinary reads should use cheap validated extraction. More expensive interpretation can help investigate changed pages, but cannot silently invent grades, dates or destinations.
- No promise of immunity to all future UI/auth changes. Detect, contain, explain and repair changes using evidence.

## Existing code: three categories

1. Reuse after verification: parsers/utilities demonstrated against representative examples.
2. Redesign around stronger boundaries: authentication, retrieval coordination, caching, result schemas and errors.
3. Retire: duplicate presentation, obsolete paths and helpers with hidden unrelated fetches.

Before carrying code into v2, answer: Why does it exist? What does it depend on? What does it guarantee? What happens when it fails? What evidence checks it?

## Build method

Understand portal capabilities and capture representative states; define contracts and failure behavior; build one complete slice (connection → verified access → classes → compact tool result → simple widget); expand one capability at a time. Do not finish the entire backend before testing the actual ChatGPT experience. Replace old capabilities only after verification.

Maintain four references: portal capability map, retrieval dependency ledger, evidence catalogue, and user-question-to-data matrix. Observable portal behavior is not knowledge of ManageBac's internal backend architecture.

## Preserved findings and suggestions

- ARCHITECTURE_REVIEW.md: original source-backed finding table, snapshot bundle proposal, layered extraction strategy, cost model, onboarding and design gates.
- PROBLEM_REGISTER.md: all 18 follow-up findings with evidence state, the retrieval table, four offline reproductions and public research suggestions.
- BACKLOG.md: original product notes and status tracking.
- MODEL_CONTEXT_DEBUG_PLAN.md: new requirement to inspect exactly what our tool sends, replay fixtures, and evaluate tool selection before visual polish.

## User priorities added in this turn

Correct and sufficient AI context matters more than debug-tool beauty. The user wants to inspect actual extracted data and outgoing model-facing payloads, not blindly trust a success message. Develop against a private static/replay source, then use the real source through the same pipeline. Tool descriptions and shared context must make capabilities understandable; remove useless tools and evaluate selected writes separately. Consult official OpenAI guidance before designing this boundary.
