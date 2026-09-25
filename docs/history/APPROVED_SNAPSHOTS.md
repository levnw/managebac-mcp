# Approved source snapshots

## 02-get-classes (current retrieval snapshot)

Location: /Users/server/Desktop/ManageBac-V2/Approved/02-get-classes/.
Created 2026-09-13 at the user's instruction. Preserves full-list class retrieval,
plain JSON contract, MCP adapter and required shared source. README documents exact
description, file ownership, connections, bounds and pending integration. Source
only; no accounts, reports, credentials or installed dependencies. Public ChatGPT
connectivity and widgets remain future work. Working is still the running app.

User instruction, 2026-09-08: retain working code separately after the user confirms approval. Source snapshots are not an independent deployment or a claim that the entire app is production-ready. Do not modify an existing snapshot during experiments; create the next numbered snapshot following approval.

## 01-login-classes

Location: /Users/server/Desktop/ManageBac-V2/Approved/01-login-classes/

Approval scope: email-based school discovery and logo, password login confirmed by protected access, enrolled-class pagination/count check. UI aesthetics, OAuth/MCP connectivity and other school capabilities are not approved/completed. Supporting web/store/UI source is included to preserve the functional slice, not to imply UI approval.

Contains seven source files only. No dependencies, virtual environments, package manifests, databases, passwords, cookies, tokens or academic data. Source still requires external Python packages to run; excluding installed dependencies does not make it dependency-free.

Structural change in this snapshot: explicit check registry in onboarding/checks.py. Login invokes a generic runner. Only classes are registered; task/comment stubs removed. Future reviewed, read-safe capability checks register here without modifying login. Automatic execution means execution of the explicit registry, not arbitrary file discovery.

Class records are retained in the temporary browser-scoped server session and returned through /api/state and the inspector. Not persisted to disk; lost when the session expires/restarts. No retroactive recovery of the previous discarded run. Current-scope readiness is not full-portal readiness; ChatGPT connection remains disabled. Existing database readiness values are not retroactively changed.

Verification: 21 tests pass after these changes. Live login/class result was observed before refactoring; the new registry wiring is tested with fixtures/mocks, not a fresh password attempt.
