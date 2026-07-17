# ChatGPT Apps SDK — Complete Reference

_Compiled 2026-07-16 by directly reading all 27 pages of developers.openai.com/apps-sdk (raw
markdown source, fetched in parallel by five subagents, not single-pass AI-summarized). This
supersedes the previous version of this file, which was thinner and had gone stale — most
notably it listed "no outputSchema" as an open gap, which is no longer true (see §19)._

**Purpose:** this is not a handoff note. It's the standing reference for how the ChatGPT Apps
SDK actually works, so any future tool, widget, or design decision in this repo can be checked
against it instead of re-deriving it or guessing. Section 19 maps every rule below onto our
actual code (`managebac_mcp/server.py`, `widget-preview/*.html`) as of this writing.

**Docs home:** https://developers.openai.com/apps-sdk (every page also exists at the same path
with `.md` appended for raw-markdown retrieval — use that for future re-reads, it's far more
reliable than fetching the rendered HTML page).

---

## Table of contents

1. [Architecture](#1-architecture)
2. [MCP Apps standard vs `window.openai` — read this first](#2-mcp-apps-standard-vs-windowopenai--read-this-first)
3. [Building the MCP server](#3-building-the-mcp-server)
4. [Tool descriptor reference](#4-tool-descriptor-reference)
5. [Tool results & `outputSchema`](#5-tool-results--outputschema)
6. [The widget bridge — full API](#6-the-widget-bridge--full-api)
7. [UI design guidelines](#7-ui-design-guidelines)
8. [UX principles](#8-ux-principles)
9. [State management](#9-state-management)
10. [File handling](#10-file-handling)
11. [Authentication](#11-authentication)
12. [Deployment & hosting](#12-deployment--hosting)
13. [Testing & troubleshooting](#13-testing--troubleshooting)
14. [App guidelines & submission](#14-app-guidelines--submission) — ⚠️ contains a real risk finding for this project
15. [Security & privacy requirements](#15-security--privacy-requirements)
16. [Metadata optimization (discovery tuning)](#16-metadata-optimization-discovery-tuning)
17. [Monetization / commerce](#17-monetization--commerce)
18. [Changelog highlights](#18-changelog-highlights)
19. [What this means for ManageBac MCP — gap analysis](#19-what-this-means-for-managebac-mcp--gap-analysis)

---

## 1. Architecture

```
Your MCP server  ←→  ChatGPT (the model)  ←→  Widget (iframe)
                                                    ↓
                                        JSON-RPC over postMessage
```

Three parts:
1. **MCP server** (required) — defines tools (capabilities) and, optionally, exposes widget HTML
   as a resource.
2. **Model** — decides when to call your tools based on the metadata you provide, passes
   arguments, receives results.
3. **Widget** (optional) — an HTML/JS bundle rendered in a ChatGPT-hosted iframe, if the tool
   points at one.

A minimal MCP server for the Apps SDK implements three protocol capabilities: **list tools**
(advertise name/schema/annotations), **call tools** (execute and return structured content), and
**return components** (optionally point a tool at an embedded HTML resource). A server can also
return `instructions` at initialization — server-wide guidance for cross-tool workflows, rate
limits, and constraints that don't belong on one tool's description; ChatGPT uses these for
cross-tool reasoning.

Transport is protocol-agnostic (SSE or Streamable HTTP); **Streamable HTTP is recommended.**

Why MCP specifically: discovery integration (the model reasons about your tools the same way it
does first-party ones), server-wide instructions, conversation awareness (structured content and
IDs persist across turns), multi-client support without custom code, and an extensible auth
model (OAuth 2.1, CIMD, DCR) instead of a proprietary handshake.

---

## 2. MCP Apps standard vs `window.openai` — read this first

**This is the single most important architectural fact in this document, and it's not reflected
anywhere in our current widget code.**

ChatGPT widgets used to be built entirely against a ChatGPT-specific `window.openai` JavaScript
API. That API still works, but OpenAI has since standardized the underlying mechanism as the
open **MCP Apps** spec (co-developed by OpenAI, now a spec other MCP-compatible hosts can also
implement), and **the docs now explicitly recommend building against the standard first**:

> "Build with the MCP Apps standard keys and bridge by default. Use `window.openai` when you
> need ChatGPT-specific capabilities."

The standard mechanism:
- **Transport:** JSON-RPC 2.0 over `window.postMessage` (same transport `window.openai` uses
  under the hood — this isn't a rewrite, it's a naming/method convention change).
- **Namespace:** `ui/*` methods and notifications.
- **Tool calls:** the actual MCP tool surface (`tools/call`), not a host-specific global.

**Migration/mapping table (standard → ChatGPT-specific alias):**

| Goal | MCP Apps standard | ChatGPT `window.openai` alias |
|---|---|---|
| Link a tool to a UI resource | `_meta.ui.resourceUri` | `_meta["openai/outputTemplate"]` |
| Receive tool input | `ui/initialize` + `ui/notifications/tool-input` | `window.openai.toolInput` |
| Receive tool results | `ui/notifications/tool-result` | `window.openai.toolOutput` |
| Call a tool from the UI | `tools/call` | `window.openai.callTool` |
| Send a follow-up message | `ui/message` | `window.openai.sendFollowUpMessage` |
| Update model-visible context | `ui/update-model-context` | `window.openai.setWidgetState` |

**Recommended pattern for new/rebuilt widgets:**
1. Declare the UI via `_meta.ui.resourceUri` (do this in addition to the ChatGPT alias — both
   cost nothing).
2. Use the standard bridge (`ui/*` over `postMessage`) for init, notifications, tool calls.
3. Layer `window.openai` on top **only** for capabilities that have no standard equivalent yet:
   `uploadFile`, `selectFiles`, `getFileDownloadUrl`, `requestModal`, `requestCheckout`
   (Instant Checkout).

**Extension best practice — feature-detect, don't assume:**
```js
const openai = typeof window !== "undefined" ? window.openai : undefined;
if (openai?.requestModal) {
  await openai.requestModal({ /* ... */ });
} else {
  // fallback for hosts without this extension
}
```
Avoid branching on product name ("if this is ChatGPT..."); branch on capability presence instead
— this is what keeps a widget portable to any future MCP Apps host.

**The minimal handshake a spec-compliant widget performs on load:**
```js
let rpcId = 0;
const pendingRequests = new Map();
const rpcNotify = (method, params) =>
  window.parent.postMessage({ jsonrpc: "2.0", method, params }, "*");
const rpcRequest = (method, params) => new Promise((resolve, reject) => {
  const id = ++rpcId;
  pendingRequests.set(id, { resolve, reject });
  window.parent.postMessage({ jsonrpc: "2.0", id, method, params }, "*");
});

window.addEventListener("message", (event) => {
  if (event.source !== window.parent) return;
  const message = event.data;
  if (!message || message.jsonrpc !== "2.0") return;
  if (typeof message.id === "number") {
    const pending = pendingRequests.get(message.id);
    if (!pending) return;
    pendingRequests.delete(message.id);
    message.error ? pending.reject(message.error) : pending.resolve(message.result);
    return;
  }
  if (message.method === "ui/notifications/tool-result") {
    // re-render from message.params.structuredContent
  }
}, { passive: true });

await rpcRequest("ui/initialize", {
  appInfo: { name: "my-widget", version: "0.1.0" },
  appCapabilities: {},
  protocolVersion: "2026-01-26",
});
rpcNotify("ui/notifications/initialized", {});
```
After that handshake, calling a tool from the widget is just another `rpcRequest("tools/call",
{ name, arguments })`.

---

## 3. Building the MCP server

### Registering a widget resource
```py
# MIME type must be exactly this:
mimeType = "text/html;profile=mcp-app"
```
Register the HTML as a resource (Python/`mcp` SDK shape; our `_STATIC_WIDGETS` dict in
`server.py` does the equivalent). Node equivalent uses `registerResource(server, name, uri, {},
handler)`.

### The decoupled data/render tool pattern — a real architectural recommendation we don't follow

This is the single biggest design pattern in the "build" docs that our server doesn't currently
use, and it's directly relevant to both **widget interactivity** and **context-window bloat**:

> "If you attach a widget template to every tool call, ChatGPT can re-render your iframe too
> often. A better pattern is to separate data-processing tools from render tools."

- **Data tools** — fetch/compute/mutate, return `structuredContent` only, **no** widget template
  attached. Fully chainable — the model can reason over the result before deciding what to do
  next.
- **Render tools** — take *already-fetched* data as input and attach the widget template
  (`_meta.ui.resourceUri` / `_meta["openai/outputTemplate"]`). Only these carry a UI.

Recommended call flow: model calls the data tool → gets `structuredContent` → model (optionally
filters/reasons over it) → model calls the render tool with the prepared data → widget renders
**once** with final, model-checked context.

Worked example from the docs (real estate): a broad `search` tool returns candidate listing IDs
+ metadata (no widget). The user asks a follow-up ("which are in the Richmond Primary School
zone?") that the backend can't filter for — the *model* narrows the ID list using data it
already has, then calls `render_listings_widget` with only the filtered IDs. The widget only
ever renders the final, correct set — never an intermediate one.

Other stated best practices for this split:
- Keep data tools reusable, returning complete `structuredContent` for chaining.
- Keep render tools presentation-only — no business logic in the render handler.
- State the dependency explicitly in the render tool's description (e.g. "Always call
  `roll_dice` first").
- For **local UI interactions** that need fresh data (a "re-roll" button, pagination, a filter
  toggle), have the widget call the data tool **directly** via `callTool`/`tools/call` — don't
  remount the whole widget by triggering a new render-tool call from the model.

This last point is exactly the mechanism for "make widget buttons feel interactive": a button
that calls a data tool directly and re-renders in place (no model round-trip, no flash) feels
alive; a button that can only ever trigger a brand-new top-level tool call from the model does
not.

### MCP server requirements (relevant even before submission)
- Publicly reachable over HTTPS with low-latency streaming on `/mcp`.
- A defined Content-Security-Policy naming the exact domains the app fetches from.
- No local/testing endpoint used for the reviewed submission (see §14).

---

## 4. Tool descriptor reference

Base fields follow the MCP spec (`tools#tool`: `name`, `description`, `inputSchema`, etc.).
Everything below is the Apps-SDK-specific layer on top.

### `_meta` fields on the **tool descriptor**

| Key | Type | Notes |
|---|---|---|
| `_meta.ui.resourceUri` | string (URI) | **Standard.** Links the tool to its UI template. |
| `_meta.ui.visibility` | string[] | Default `["model", "app"]`. Restrict to just one side if a tool should only be callable from the widget, not the model, or vice versa. |
| `_meta["openai/outputTemplate"]` | string (URI) | ChatGPT alias of `ui.resourceUri`. Set both. |
| `_meta["openai/widgetAccessible"]` | boolean | Legacy; default `false`. **Required `true` on any tool a widget calls via `callTool`/`tools/call`** — this applies generally, not just to specific example tools. Prefer `ui.visibility` going forward but this still gates the ChatGPT-specific call path. |
| `_meta["openai/visibility"]` | string | Legacy compat field (`public`/`private`); prefer `ui.visibility`. |
| `_meta["openai/toolInvocation/invoking"]` | string | **Max 64 characters.** Status text shown while the tool runs. |
| `_meta["openai/toolInvocation/invoked"]` | string | **Max 64 characters.** Status text shown after completion. |
| `_meta["openai/fileParams"]` | string[] | Top-level input fields that are files (see §10). |
| `_meta["securitySchemes"]` | array | Back-compat mirror for clients reading only `_meta`. |

### Annotations (tool descriptor, sibling of `_meta`)

All four are read by ChatGPT to decide confirmation-prompt behavior, and **incorrect/missing
annotations are called out explicitly as a common cause of App Store rejection.** They do
**not** replace server-side authorization — they're UI framing only.

| Annotation | Type | Required for submission? | Meaning |
|---|---|:---:|---|
| `readOnlyHint` | boolean | **yes** | `true` only if the tool strictly reads/looks up/lists and never mutates, sends, or triggers anything. |
| `destructiveHint` | boolean | **yes** | `true` if it can cause an irreversible outcome (delete, overwrite, unrecoverable send), even conditionally or via defaults. |
| `openWorldHint` | boolean | **yes** | `true` if it writes to or changes anything visible outside the user's own account/private system (posting, emailing externally, publishing). |
| `idempotentHint` | boolean | no | `true` if calling again with identical args has no additional effect. |

### `_meta` fields on the **UI resource** (set via `registerResource`, not the tool)

| Key | Type | Purpose |
|---|---|---|
| `_meta.ui.prefersBorder` | boolean | Hint to render inside a bordered card. |
| `_meta.ui.csp` | object | `{ connectDomains: string[], resourceDomains: string[], frameDomains?: string[] }`. `frameDomains` defaults to none and enables nested iframes — triggers stricter review, avoid unless essential. |
| `_meta.ui.domain` | string (origin) | Dedicated origin for hosted components. **Required for plugin submission.** Defaults to `https://web-sandbox.oaiusercontent.com`. |
| `_meta["openai/widgetDescription"]` | string | Human-readable summary shown to the model on component load — reduces redundant narration in the model's follow-up text. |
| `_meta["openai/widgetCSP"]` | object | Legacy ChatGPT-compat CSP (snake_case: `connect_domains`, `resource_domains`, `frame_domains?`). **Still required** for `redirect_domains` (see `openExternal` below) — the standard `ui.csp` shape has no equivalent field. |
| `_meta["openai/widgetDomain"]` | string | Alias of `ui.domain`. |

### Tool results

| Key | Required? | Visible to | Notes |
|---|:---:|---|---|
| `structuredContent` | no | model + widget | Must match `outputSchema`. |
| `content` | no | model + widget | Text/other content blocks. |
| `_meta` | no | **widget only** | Hidden from the model entirely — use for UI hydration data the model doesn't need to reason about. |

**Host-provided tool-result `_meta`:** `_meta["openai/widgetSessionId"]` — a stable per-mounted-
widget-instance ID, useful for correlating logs/calls until the widget unmounts.

**Error results:** `_meta["mcp/www_authenticate"]` (string or string[]) — RFC 7235
`WWW-Authenticate` challenge, this is what triggers ChatGPT's OAuth re-auth flow on a 401.

### `_meta` fields **ChatGPT sends you** on tool calls

| Key | When | Purpose |
|---|---|---|
| `_meta["openai/locale"]` | init + every call | Requested locale (BCP 47). Legacy alias `_meta["webplus/i18n"]`. |
| `_meta["openai/userAgent"]` | every call | Best-effort UA hint — **never** use for authorization. |
| `_meta["openai/userLocation"]` | every call | Coarse hint: city/region/country/timezone/lat/long — also never for authorization. |
| `_meta["openai/subject"]` | every call | Anonymized user ID, for rate limiting. |
| `_meta["openai/session"]` | every call | Anonymized conversation ID — correlates tool calls within one ChatGPT session. |
| `_meta["openai/organization"]` | every call | Anonymized org ID, when available. |

Explicit caveat from the docs: `userAgent`/`userLocation` are hints only; servers must tolerate
their absence and never gate behavior on them.

---

## 5. Tool results & `outputSchema`

**`outputSchema` should be declared for any tool returning `structuredContent`** — it describes
the exact returned shape so the client can validate and so the model can reason about follow-up
calls. Node/Zod example from the docs:
```ts
outputSchema: {
  results: z.array(z.object({ id: z.string(), title: z.string(), url: z.string() })),
}
```
No documented hard size limit on `outputSchema` itself, but **`structuredContent` has a real,
undocumented practical ceiling** — ChatGPT silently drops oversized `structuredContent` and
falls back to plain text with no widget and no error. Empirically (from this project's own
history) that ceiling is roughly **4–5 KB**. There is no official number in the docs; treat ours
as the operative constraint.

---

## 6. The widget bridge — full API

### `ui/*` (MCP Apps standard — build against this)

| Category | Method/notification | Purpose |
|---|---|---|
| Tool input | `ui/notifications/tool-input` | Latest invocation args. For approval-gated tools, arrives **only after** user approval — don't assume input is present on first render. |
| Tool results | `ui/notifications/tool-result` | Latest output: `content`, `structuredContent`, `_meta`. |
| Tool calls | `tools/call` | Widget-initiated tool invocation. |
| Follow-up message | `ui/message` | Post a component-authored message into the transcript. |
| Model context | `ui/update-model-context` | Push widget-state changes into what the model can see. |

### `window.openai` (ChatGPT extension layer)

**State & data:**

| Property/Method | Type | Notes |
|---|---|---|
| `toolInput` | object \| null | `null` until `ui/notifications/tool-input` fires for approval-gated tools. |
| `toolOutput` | object | The `structuredContent`. |
| `toolResponseMetadata` | object | Full result envelope incl. hidden `_meta` (`status`, `call_tool_result`, `mcp_tool_result`, `_meta`). |
| `widgetState` | object | Persisted UI state snapshot, survives re-renders. |
| `setWidgetState(state)` → void | function | Store synchronously; call after every meaningful interaction. |

**Actions:**

| Method | Signature | Returns | Purpose |
|---|---|---|---|
| `callTool` | `(name, args)` | Promise | Invoke an MCP tool from the widget. Target tool needs `openai/widgetAccessible: true`. |
| `sendFollowUpMessage` | `({prompt, scrollToBottom?})` | Promise | `scrollToBottom` defaults `true`. |
| `requestDisplayMode` | `({mode})` | Promise | `"inline" \| "pip" \| "fullscreen"`. On mobile, PiP is coerced to fullscreen. |
| `requestModal` | `({params, template?})` | Promise | Host-owned modal. Omit `template` to reuse current; pass a different registered `ui://` URI to show alternate content. |
| `requestClose` | `()` | Promise | Also settable server-side via result `metadata["openai/closeWidget"]: true`. |
| `notifyIntrinsicHeight` | `(height)` | void | Report real pixel height — avoids clipping. Call after every render. |
| `openExternal` | `({href, redirectUrl?})` | Promise | Use instead of `window.open`. `redirectUrl: false` skips default param appending. For return-to-chat flows (checkout etc.), add the destination origin to `openai/widgetCSP.redirect_domains` — ChatGPT then skips the safe-link modal and appends its own `redirectUrl` param to route the user back. |
| `setOpenInAppUrl` | `({href})` | void | Overrides the fullscreen "Open in App" target. |

**Files (all ChatGPT-only, no standard equivalent):**

| Method | Returns | Notes |
|---|---|---|
| `uploadFile(file, {library?})` | `{fileId}` | `{library: true}` also saves to the user's file library, when available. |
| `selectFiles()` | `[{fileId, fileName, mimeType}]` | Picker over already-uploaded library files, pre-authorized. Feature-detect — library isn't available to every user/environment; fall back to `uploadFile`. |
| `getFileDownloadUrl({fileId})` | `{downloadUrl}` | Temporary URL. Works for widget-uploaded, library-picked, tool-input-file, or tool-result-file references. |

**Context (read-only/subscribable):** `theme`, `displayMode`, `maxHeight`, `safeArea`, `view`,
`userAgent`, `locale`.

**Subscribing to changes (React pattern from the docs):**
```ts
export function useOpenAiGlobal<K extends keyof WebplusGlobals>(key: K): WebplusGlobals[K] {
  return useSyncExternalStore(
    (onChange) => {
      const handler = (event) => { if (event.detail.globals[key] !== undefined) onChange(); };
      window.addEventListener("openai:set_globals", handler, { passive: true });
      return () => window.removeEventListener("openai:set_globals", handler);
    },
    () => window.openai[key],
  );
}
```

**Widget session correlation:** result `_meta["openai/widgetSessionId"]` — stable per mounted
widget instance, for tying logs/calls together while it stays mounted.

**File-input schema requirement** — to accept files as tool input, list the top-level field
names in `_meta["openai/fileParams"]`. Each such field's schema must declare exactly these four
properties (only `download_url`/`file_id` required, no other properties may be marked required):
`download_url` (string), `file_id` (string), `mime_type` (string, optional), `file_name` (string,
optional). Runtime shape is snake_case:
```json
{"download_url": "https://...", "file_id": "file_...", "mime_type": "image/png", "file_name": "input.png"}
```

---

## 7. UI design guidelines

Full design system reference: https://openai.github.io/apps-sdk-ui/ (Tailwind + CSS variable
tokens + accessible component library — not required, but faster and automatically consistent
with ChatGPT's own look). Figma library also published.

### Display modes

Every app starts **inline**; other modes are requested, not default.

**Inline card** — lightweight, single-purpose. Use for one action/decision, small structured
data, or a fully self-contained widget.
- **Max two actions**, placed at the bottom: one primary CTA, one optional secondary.
- **No deep navigation** — no tabs, no drill-ins, no multi-view inside one card. Split into
  separate cards/tool calls instead.
- **No nested scrolling** — the card auto-fits its content (up to mobile viewport height), it
  doesn't scroll internally.
- **No duplicating ChatGPT's own UI** (don't rebuild the composer, etc.).
- Simple inline-editable text is fine for quick edits; edits persist as state.

**Inline carousel** — side-by-side cards for scanning/choosing among similar items.
- **3–8 items** per carousel.
- Always include an image/visual per item.
- Metadata: 2–3 lines max (the doc states both "avoid more than two lines" and "three lines max"
  in different spots — treat 2 lines as the target, 3 as the hard ceiling).
- One optional CTA per item.

**Fullscreen** — for rich tasks that don't fit a card (explorable map, rich editing canvas,
detailed browsing like listings/menus). ChatGPT's composer stays overlaid on top — design your
UX assuming the user can keep typing prompts *while* fullscreen is open; that's not an edge
case, it's the primary interaction model for fullscreen. Request via
`requestDisplayMode({mode: "fullscreen"})`.

**Picture-in-picture** — persistent floating panel for ongoing/live sessions (games, quizzes,
timers) that keep running while the conversation continues and can react to chat input.
- Pins to top of viewport on scroll; stays until dismissed or session ends.
- **Close it automatically when the session ends** — don't leave a stale PiP hanging.
- Don't overload it with controls better suited to inline/fullscreen.
- On mobile, PiP is coerced to fullscreen.

### Visual design

- **Color:** system palette for text/icons/dividers. Brand accents only on primary buttons,
  logos, or icons — **never on backgrounds or body text colors.** No custom gradients/patterns.
- **Typography:** always inherit the system font stack (SF Pro / Roboto) — **no custom fonts,
  even in fullscreen.** Limit font-size variation; prefer body/body-small sizes. Partner
  styling (bold/italic/highlight) only inside content areas, never for structural UI.
- **Spacing:** system grid spacing, consistent padding, respect system corner radius, keep a
  clear headline → supporting text → CTA hierarchy.
- **Icons/imagery:** monochromatic, outlined iconography only. **Do not include your logo in the
  response — ChatGPT appends it automatically** above the widget. Imagery must respect enforced
  aspect ratios.
- **Accessibility:** WCAG AA contrast minimum, alt text on every image, layouts must survive
  text resizing without breaking.

---

## 8. UX principles

The core test, verbatim: **an app should do at least one thing *better* because it lives in
ChatGPT** — via conversational leverage (natural language + thread context unlocks things a
traditional UI can't), native fit (feels embedded, not bolted-on), and composability (small
reusable actions the model can mix with other tools).

Five design rules:
1. **Extract, don't port.** Don't mirror your full website/app — pull out a handful of atomic
   actions, each exposing the minimum inputs/outputs the model needs to act confidently.
2. **Design for conversational entry** — users arrive with open-ended prompts, direct commands,
   *or* need first-run onboarding. Support all three.
3. **Design for the ChatGPT environment** — use UI only to clarify actions/capture input/present
   results. Skip anything ornamental that doesn't advance the current task.
4. **Optimize for conversation, not navigation** — the model owns state/routing; your job is
   clear declarative actions and concise responses (tables/lists/short paragraphs), not
   dashboards.
5. **Embrace the ecosystem** — accept natural language over form fields, personalize from
   conversation context, compose with other apps when it genuinely saves the user effort.

### Pre-publish checklist (self-assessment, not a guarantee of approval)
- Does at least one capability rely on ChatGPT's actual strengths (NL, thread context,
  multi-turn)?
- Does the app provide something the user can't get from base ChatGPT (proprietary data,
  specialized UI, guided flow)?
- Are tools atomic, self-contained, explicit about inputs/outputs?
- **Would replacing every custom widget with plain text meaningfully degrade the experience?**
  If not, the widget shouldn't exist.
- Can a user finish at least one meaningful task fully in-chat?
- Is it fast enough to keep the chat's rhythm?
- Can you imagine confident trigger prompts?
- Does it lean on platform behaviors (rich prompts, memory, multi-tool composition)?

**Explicit anti-patterns:** long-form/static content better suited to a website; complex
multi-step workflows that exceed inline/fullscreen; ads/upsells/irrelevant messaging; sensitive
info surfaced on a card others might see; duplicating ChatGPT's own system functions (e.g.
rebuilding the composer).

---

## 9. State management

Three categories, each with a different home:

| Type | Lives in | Mechanism |
|---|---|---|
| **Business data** | Your MCP server / backend DB | Tool calls read/write it; results return fresh snapshots. |
| **UI-only state** (selected tab, scroll position, staged form input) | The widget instance | In-memory JS state, optionally persisted via `window.openai.setWidgetState` / restored from `window.openai.widgetState`. |
| **Model-visible context** | Conversation | Push via `ui/update-model-context` (standard) so the model knows what the user did in the widget without a full re-render. |

Component initial render should come from the latest `structuredContent` delivered over
`ui/notifications/tool-result`; on a UI-initiated `tools/call`, render from that call's own
returned result directly (don't wait for a redundant notification).

---

## 10. File handling

Covered fully in §4 (file-input schema) and §6 (`window.openai` file methods). One point worth
restating: `selectFiles()` results are **pre-authorized** — no separate download-permission step
needed before calling `getFileDownloadUrl`.

---

## 11. Authentication

- Use **OAuth 2.1** authorization-code flows for external account linking.
- Prefer **Client ID Metadata Documents (CIMD)** when your auth server supports it.
- Token exchange: `none` for public clients, or `private_key_jwt` when the auth server requires
  client authentication.
- Support **Dynamic Client Registration (DCR)** when CIMD isn't available or the app creator
  chooses it — your auth server needs a `registration_endpoint`, and new clients need at least
  one login connection enabled.
- Verify/enforce scopes on **every** tool call; expired/malformed tokens → `401` with a
  `WWW-Authenticate` header (via `_meta["mcp/www_authenticate"]` on the error result) — that
  header is literally what triggers ChatGPT to restart the OAuth flow.
- Don't hold long-lived secrets client-side; use the provided auth context.

**We do not do any of this** — see §19.

---

## 12. Deployment & hosting

Local dev: tunnel your local server (ngrok, Cloudflare Tunnel, or OpenAI's own "Secure MCP
Tunnel") and point a developer-mode app at the HTTPS `/mcp` URL. Rebuild the widget bundle →
restart the server → click **Refresh** on the developer-mode app after every change (metadata is
cached until refreshed).

Named hosting partners the docs currently call out (informational, not a requirement to use any
of them): Manufact (`mcp-use` framework + Manufact Cloud), Vercel (native ChatGPT Apps hosting
support + a Next.js starter template), Alpic (Skybridge framework — local emulator, HMR, React
hooks for widget state sync), MCPcat (usage analytics SDK, host-agnostic). Generic options:
managed containers (Fly.io/Render/Railway), serverless (Cloud Run/Azure Container Apps — watch
cold-start impact on streaming), or your own Kubernetes ingress with SSE support.

Whatever you choose: `/mcp` must stay responsive, support streaming, return correct HTTP status
codes on error, and you must be able to see logs/metrics when something breaks.

**Environment/ops basics:** secrets outside the repo via a real secret manager; log tool-call
IDs + latency + error payloads; monitor CPU/memory/request counts.

**Connecting from ChatGPT (developer mode):** Settings → Security and login → Developer mode →
Settings → Plugins (or chatgpt.com/plugins) → **+** → paste HTTPS `/mcp` URL + name + description
→ Create. As of **2026-11-13, ChatGPT Apps are supported on all plans** including Business/
Enterprise/Education.

**Permission levels** the *user* controls per app (personal accounts) or the *admin* controls
workspace-wide (Business/Enterprise): **Always ask** / **Ask before making changes** / **Ask
only before important changes** (default — routine reads and writes happen automatically, only
consequential actions like send/delete/post/purchase prompt). Personal accounts additionally get
an **"Always allow"** option per confirmation prompt Business/Enterprise members don't see.

---

## 13. Testing & troubleshooting

**MCP Inspector** for local debugging: `npx @modelcontextprotocol/inspector@latest --server-url
http://localhost:<port>/mcp --transport http` (or omit `--server-url`/`--transport` and enter
interactively). Also usable directly against a deployed server. Renders components inline,
surfaces errors immediately.

**API Playground** (platform.openai.com/playground) → Tools → Add → MCP Server, for raw
request/response inspection without the full ChatGPT UI.

**Pre-launch regression checklist:** tool list matches docs (no leftover prototypes);
`structuredContent` matches declared `outputSchema` on every tool; widgets render with zero
console errors and restore state correctly; auth flows issue valid tokens and reject invalid
ones with meaningful errors; discovery behaves correctly across your full golden-prompt set
(direct/indirect/negative) with no regressions.

### Troubleshooting — symptom → cause → fix (reproduced in full, this is the highest-value table in the whole doc set)

**Server-side:**
- *No tools listed* → confirm the server's actually running and you're pointed at `/mcp`; if the
  port changed, update the connector URL and restart Inspector.
- *Structured content only, no component* → check the tool descriptor sets `_meta.ui.resourceUri`
  to a registered resource with `mimeType: "text/html;profile=mcp-app"` (ChatGPT also honors
  `_meta["openai/outputTemplate"]`), and that the resource loads without a CSP error.
- *Schema mismatch errors* → your server model (Pydantic/TS types) drifted from the declared
  `outputSchema` — regenerate types after any schema edit.
- *Slow responses* → anything over "a few hundred milliseconds" reads as sluggish; profile
  backend calls and cache.

**Widget:**
- *Widget fails to load* → check browser/Inspector console for CSP violations or missing
  bundles; confirm the HTML inlines its compiled JS and all deps are actually bundled in.
- *Drag-and-drop / edits don't persist* → confirm you call `window.openai.setWidgetState` after
  every update and rehydrate from `window.openai.widgetState` on mount.
- *Layout breaks on mobile* → inspect `window.openai.displayMode` and `window.openai.maxHeight`
  and adjust; avoid fixed heights and hover-only affordances (no hover on touch).

**Discovery:**
- *Tool never triggers* → rewrite the description to lead with "Use this when…", refresh starter
  prompts, retest against your golden prompt set.
- *Wrong tool selected* → add disambiguating detail / explicitly state disallowed scenarios in
  the description; consider splitting an overloaded tool into smaller ones.
- *Launcher ranking feels off* → refresh directory metadata, confirm icon/description match user
  expectations.

**Auth:**
- *401 errors* → response needs a `WWW-Authenticate` header so ChatGPT restarts the OAuth flow;
  double-check issuer URLs and audience claims.
- *Client registration fails* → for CIMD, confirm your auth server metadata sets
  `client_id_metadata_document_supported: true` and can fetch ChatGPT's client metadata doc; for
  `private_key_jwt`, confirm it can fetch ChatGPT's JWKS and validate the signed assertion; for
  DCR, confirm a working `registration_endpoint` and that new clients get a login connection.

**Deployment:**
- *ngrok tunnel times out* → restart it, confirm the local server's actually up first; use a
  real hosting provider with health checks for anything beyond dev.
- *Streaming breaks behind a proxy* → your load balancer/CDN needs to allow SSE/streaming
  responses without buffering them.

**Escalation path** (if all the above checks out and it's still broken): collect server logs +
component console logs + the ChatGPT tool-call transcript + screenshots, note the exact prompt
and any confirmation dialogs shown, then contact your OpenAI partner contact.

---

## 14. App guidelines & submission

**⚠️ Real finding for this project, not a hypothetical:** the app guidelines explicitly say —

> Apps that are primarily unofficial connectors to third-party services are not approved. No
> pass-through middleware layers. Apps must not scrape external sites, relay queries, or
> integrate third-party APIs without proper authorization/compliance with that service's terms.

**ManageBac MCP is, structurally, exactly that pattern** — it has no official ManageBac API
relationship; it logs in as the student and scrapes ManageBac's rendered HTML. This doesn't mean
the project is dead on arrival for App Store submission, but it means **"submit to the ChatGPT
App Store" cannot be treated as a routine checklist item** the way outputSchema or CSP domains
are — it may require an actual authorization/partnership conversation with ManageBac (the
company) before OpenAI would approve a public listing, independent of code quality. This is
worth raising explicitly in the product-direction discussion (ties into GitHub issue #55 "how
are we different from ManageBac's own app" and the legal-blocker issues #51/#52) — it's a
distinct risk from those, not the same one, and nothing in the existing HANDOFF docs or GitHub
issues currently flags it.

### Submission model (as of this writing)
Apps are now submitted and published **as plugins** — you build the app's MCP server with the
Apps SDK, then submit a plugin containing it through the plugin submission portal
(platform.openai.com/plugins). "Developer mode" (§12) is for private/workspace-internal use only
— that flow does *not* require submission at all.

### Prerequisites before submitting
- **Organization verification** on the OpenAI Platform Dashboard — individual verification if
  publishing under a personal name, business verification if publishing under a company name.
  Enforced at review; publishing under an unverified name is an automatic rejection.
- `api.apps.write` permission to submit, `api.apps.read` to view draft/review status
  (organization owners have both by default, can grant to others via Dashboard roles).
- MCP server publicly hosted (no local/test endpoint), with a defined CSP naming the exact
  domains it fetches from.
- Most apps submit a **universal** MCP server URL (one endpoint for everyone). **Template** URLs
  (per-workspace/tenant endpoints, `{placeholder}` syntax) are only for apps with genuinely
  workspace-specific endpoints.

### Review flow
Add server details (+ OAuth creds if applicable) → **Scan Tools** (imports your live metadata:
names, descriptions, schemas, security schemes, `_meta`, annotations, linked UI/CSP, server
`instructions`) → fill in name/logo/description/company+privacy-policy URLs/test prompts+
expected responses/localization/optional screenshots (screenshots **only** for apps with a UI) →
**Submit for review**. Only one version may be published, and only one may be in review, at a
time per app. **EU-data-residency projects currently cannot submit** — use a global-residency
project.

### Most common documented rejection reasons (verbatim causes, from the docs' own FAQ)
1. **Can't connect to your MCP server / test credentials don't work** — reviewers need a demo
   account with zero extra config: no MFA, no SMS/email verification step, credentials that work
   outside any internal network, not expired.
2. **Test cases don't produce correct results** — rerun every declared test case, check for
   loading/image/UI errors, make sure output stays tightly scoped to the request (no irrelevant
   extra info, no leaked personal identifiers), verify parity on both web and mobile.
3. **Returns undisclosed user-related data types** — audit real tool responses for anything not
   covered by your published privacy policy; strip telemetry/internal IDs
   (session/trace/request IDs, timestamps, internal account IDs) and any secrets; if a user
   identifier really is needed, it must be explicitly tied to the user's stated intent, not
   "looked up and echoed" as a side effect.
4. **Annotation/behavior mismatch** — `readOnlyHint` must be `true` only for pure fetch/list/get
   with zero side effects; `destructiveHint` `true` for anything irreversible (with your
   justification explaining exactly what's irreversible and any safeguards like dry-run or
   confirmation); `openWorldHint` `true` for anything touching the public internet or systems
   outside the user's private account. **Your written justification does not override the
   annotation** — if you claim a tool is "functionally read-only" but it has `readOnlyHint:
   false`, that's still a rejection; fix the annotation, re-scan, resubmit.

### Metadata versioning after publish
Published app metadata is a **versioned contract**, frozen at whatever was captured the moment
you hit "Scan Tools" for that submitted version — your *live* server keeps serving real tool
calls and UI resources, but the *published* tool list/schema/annotations users see stays pinned
to the reviewed snapshot until you publish a new approved version.

| Change | What you must do | When users see it |
|---|---|---|
| Tool list/names/descriptions/schemas/annotations/security schemes/`_meta`/server `instructions` | Deploy → new draft version → Scan Tools → submit → publish after approval | Only after you publish the approved version |
| UI resource URI or CSP | Same as above | Same as above |
| Backward-compatible content change at the **same** published UI resource URI | Just deploy | Immediately (may be cached up to ~1h) |
| Server-only fix / live tool result / result `_meta` change that preserves the published contract | Just deploy | Immediately, through the live endpoint |
| MCP server origin (scheme/host/port) change | Requires a **new app** entirely, full resubmission | After the new app is approved+published |

**Breaking changes to a published app are not supported** — removing/renaming a tool, an
incompatible schema change, or breaking a published UI resource URI can break the live version
the moment you deploy it. Add new tools/fields/resources alongside the old contract instead, and
roll back immediately if a deploy breaks the published version rather than waiting on a new
review.

### Full prohibited-goods/commerce list, and safety/privacy rules
See §15 and §17 — kept there since they're really "policy surface," not submission mechanics.

---

## 15. Security & privacy requirements

**Principles:** least privilege (request only scopes/storage/network actually needed), explicit
user consent for account linking and write access, defense in depth (assume prompt injection and
malicious input reach your server — validate everything server-side regardless of what the model
claims, keep audit logs).

**Data handling:** `structuredContent` should include only what the current prompt needs — never
embed secrets/tokens in it. Define and publish a retention period; honor deletion requests
promptly. Redact PII before logging; keep correlation IDs for debugging but avoid storing raw
prompt text unless genuinely necessary.

**Prompt injection / write actions:** developer mode grants full MCP access including write
tools — mitigate by writing explicit negative guidance into tool descriptions (e.g. "Do not use
to delete records"), validating every input server-side even when the model supplied it,
requiring human confirmation on irreversible operations, and sharing your best
injection-probing prompts with QA early.

**Sandbox restrictions on widgets (not configurable):** widgets run in a strict-CSP sandboxed
iframe with **no access to** `window.alert`, `window.prompt`, `window.confirm`, or
`navigator.clipboard`. `fetch` only works within CSP bounds. Sub-iframes are blocked unless
explicitly enabled via `frameDomains` (and doing so triggers extra review, see §14).

**Auth:** see §11 in full — this section just adds "verify/enforce scopes on every call, don't
hold long-lived secrets client-side."

### Privacy — the concrete data rules (this is the section most relevant to our `submitted_files`, `secret.key`, and cache design)

- **Restricted data you must never collect/process at all:** PCI-DSS payment card data,
  protected health information (PHI), government identifiers (SSNs etc.), or credentials/auth
  secrets (API keys, MFA/OTP codes, passwords).
- **Data minimization on input:** request only what's strictly needed for that tool's function;
  no "just in case" broad-profile fields.
- **Response minimization on output:** return only data directly relevant to the request; strip
  diagnostic/telemetry/internal identifiers (session/trace/request IDs, timestamps, logging
  metadata) unless truly required.
- **Location data:** don't request raw coordinates/city directly in an input schema — pull
  location via the client's own controlled side channel instead, to preserve the user's consent
  boundary.
- **No reconstructing the chat log:** an app must not pull or infer the full conversation history
  from the client — operate only on the explicit snippets/resources actually sent to it.
- A published, accurate **privacy policy** is required regardless of submission status if you're
  handling real user data at all: categories of data collected, purpose, recipients, retention
  timeline, user controls offered.

---

## 16. Metadata optimization (discovery tuning)

Discovery is model-driven — the model picks your tool based on metadata quality, not a fixed
routing table. Process the docs recommend:

1. **Build a golden prompt set** before touching code: 5+ **direct** prompts (user names your
   product/data explicitly), 5+ **indirect** prompts (user states a goal, not a tool name), and
   **negative** prompts (should never trigger your app) — these three categories together let
   you measure both recall and precision instead of just recall.
2. **Write tool names as `domain.action_verb`** (`calendar.create_event`, not `create_event`) —
   avoids ambiguity once multiple connectors are active in one chat.
3. **Descriptions start with "Use this when…"** and explicitly state disallowed cases ("Do not
   use for reminders").
4. **Set annotations correctly** even before submission matters — they shape ChatGPT's
   confirmation-prompt behavior today, not just review outcomes later.
5. **Evaluate in developer mode**, replaying the whole golden prompt set, logging which tool got
   picked / what args were passed / whether the widget rendered — track precision and recall
   separately.
6. **Change one metadata field at a time** so you can attribute an improvement (or regression)
   correctly; keep a dated revision log.
7. **Monitor production** — a spike in "wrong tool" corrections from users usually means metadata
   has drifted from actual behavior; re-run the golden set after any schema or tool-list change.

---

## 17. Monetization / commerce

Not currently relevant to ManageBac MCP (no payments anywhere in this project), documented here
for completeness since it's part of the same policy surface as §14.

**Allowed:** commerce for **physical goods only**, via external checkout that redirects to the
seller's own domain, or (beta, invite-only) OpenAI's Instant Checkout for approved partners using
a `checkout_session` tool + `ui://widget/checkout-session.html` widget, input shape
`{items: [{id, quantity, offerId}]}`.

**Explicitly prohibited, in full:** adult content/sexual services; real-money gambling; illegal
or regulated drugs and paraphernalia; prescription/age-restricted medications; counterfeit goods,
stolen goods, fraud tools, piracy tools, wildlife contraband; malware/spyware/stalkerware/covert
surveillance hardware; tobacco/nicotine products; firearms/explosives/illegal weapons/self-
defense weapons/extremist merchandise; fake IDs, debt-relief/credit-repair schemes, deceptive
financial services, executing money/crypto transfers or trades directly, government-service
impersonation, identity-theft-enabling services, fraud-facilitating legal services, consent-
bypass telemarketing, high-chargeback travel services. **No digital goods/subscriptions/
credits/tokens sold through an app at all** — commerce is physical-goods-only, full stop. No ads,
no upsells, no app existing primarily as an ad vehicle.

Also relevant to a possible future restaurant-booking-style feature (**not** currently in scope,
noted for completeness): a separate beta **Restaurant Reservation** spec exists
(`restaurant_reservation` tool + `ui://widget/restaurant-reservation.html`, backed by a
`GET /v1/businesses` feed API with required `id/name/address/location/phone_number/website_url/
platform_url` fields) — restricted to approved partners via application.

---

## 18. Changelog highlights

Most recent first, dates as published on the docs' own changelog:

- **2026-06-12** — Users get three permission levels per app (always ask / ask before changes /
  ask only before important changes); Business/Enterprise admins set workspace + per-app
  defaults.
- **2026-05-28** — ChatGPT now delivers **standardized CSS variables** via
  `hostContext.styles.variables` at init, updated live on theme change via
  `ui/notifications/host-context-changed` — this is the correct mechanism for automatic dark-mode
  support without hardcoding colors (referenced but not detailed in the earlier version of this
  doc; now confirmed as a real, shipped API).
- **2026-05-27** — `window.openai.toolResponseMetadata` now carries the full result envelope
  including hidden `_meta`. Approval-gated tools now deliver widget input via the
  `ui/notifications/tool-input` lifecycle event (post-approval) instead of preloading it.
- **2026-05-26** — ChatGPT started reading server-wide `instructions` at init for cross-tool
  context.
- **2026-05-06** — Docs began showing `outputSchema` in examples and recommending it broadly
  (this is presumably close to when we first added it, per our own git history).
- **2026-03-24** — `selectFiles()` and `uploadFile(file, {library: true})` introduced.
- **2026-03-09** — `uploadFile` expanded beyond images to arbitrary file types.
- **2026-02-22** — ChatGPT reached full MCP Apps spec compatibility.
- **2026-02-02** — `redirectUrl: false`, `setOpenInAppUrl()`, `openai/widgetDescription`
  precedence, `scrollToBottom` on follow-up messages all added.
- **2026-01-15** — `_meta["openai/session"]` added to tool calls; `requestModal()` gained
  template-switching.
- **2025-11-04** — First state-management guide published; unified developer changelog launched.

---

## 19. What this means for ManageBac MCP — gap analysis

Checked directly against `managebac_mcp/server.py` and `widget-preview/*.html` on 2026-07-16.

### Already correct / no action needed
- **`outputSchema` is implemented on all 14 tools** (`server.py:1207-1225`) — the "no
  outputSchema" gap in the previous version of this doc, and GitHub issue #24, are both **stale**.
  Worth closing #24 with a note.
- **`_meta.ui.resourceUri` and `_meta.ui.csp` are already set** alongside the ChatGPT-alias keys
  (`_widget_meta()` in `server.py:764`) — we're not purely on the legacy path, we did already
  adopt the standard `_meta` shape for resource linking and CSP.
- **`mimeType: "text/html;profile=mcp-app"`** is used correctly.

### Real gaps, in priority order

1. **No widget uses the `ui/*` standard bridge at all.** All four widgets
   (`task-card.html`, `grades-card.html`, `timetable-card.html`, `class-files.html`) read
   `window.openai.toolOutput` directly and nothing else — no `ui/initialize` handshake, no
   listening for `ui/notifications/tool-result`. This works today only because ChatGPT still
   supports the legacy path, but it's explicitly the *not-recommended-for-new-work* pattern per
   §2, and it's the reason none of the interactive APIs below are wired in either — there's no
   bridge plumbing to call them through in the first place.
2. **No `callTool`/`tools/call` from any widget** — confirmed via direct grep, zero matches.
   Every button in every widget is inert. This is the direct fix for "make the buttons feel more
   interactive" — per §3's decoupled pattern, a button should call a data tool directly and
   re-render locally, not require a whole new model-initiated tool call.
3. **No `setWidgetState`/`widgetState`** — tab/filter/scroll position resets on every re-render.
4. **No `notifyIntrinsicHeight`** — widgets can clip at the wrong height; never called.
5. **No `requestDisplayMode`** — nothing ever asks for fullscreen, even though §7 says fullscreen
   is specifically for cases like a file browser or timetable grid, which describes two of our
   four widgets.
6. **No `readOnlyHint`/`destructiveHint`/`openWorldHint`/`idempotentHint` on any of the 14
   tools** — confirmed via grep, zero matches anywhere in `server.py`. Every tool is read-only
   except `submit_task_file`; none of that is currently declared. Cheap to fix, and per §14 it's
   an explicit rejection cause if we ever submit.
7. **No decoupled data/render tool split** — `get_task_detail`, `get_files`, `get_grades`,
   `get_timetable` each fetch *and* attach a widget template in one call. Per §3, this is fine
   functionally but is the documented cause of "ChatGPT re-renders the iframe too often" and
   blocks the "call a data tool directly from a button" interaction pattern in point 2 above.
   Worth reconsidering when the widgets get rebuilt to the new visual direction anyway.
8. **No dark mode** — none of the widgets read `hostContext.styles.variables` (§18,
   2026-05-28) or `window.openai.theme`. This API didn't exist when the original gap was logged;
   it does now and is the documented fix.
9. **No OAuth** — we use a custom `?key=` token, not the OAuth 2.1/CIMD/DCR flow in §11. Already
   tracked as a "Next" roadmap item; nothing new here, just confirming the doc's exact
   requirements if/when it's tackled.
10. **`structuredContent` size discipline is inconsistent** — some tools already slim
    aggressively (`_widget_sc()` for task cards, `_slim_tasks()` for the get_tasks token-bloat
    fix), but there's no single documented budget or systematic per-tool audit. §5's ~4-5KB
    practical ceiling should be checked against all four widget-producing tools, not just the
    ones that have already needed a fix.

### The one strategic-risk finding (§14)
Worth its own line here since it's easy to miss buried in §14: **this project's core mechanism
(scraping ManageBac without an official API relationship) is the exact pattern OpenAI's app
guidelines say gets rejected as an "unofficial connector."** This doesn't block anything about
local/ChatGPT-connector usage today (that's developer-mode style usage, not a public plugin
listing), but it means "submit to the App Store" isn't a pure engineering checklist item the way
outputSchema or CSP domains are — flag this explicitly in any product-direction discussion.

### Update — 2026-07-16, backend fixes actioned on `design-refresh`

Three of the items above were picked up and resolved (or deliberately deferred with reasoning)
in the same session this doc was written:

**1. Annotations — done.** All 14 tools now carry `readOnlyHint`/`destructiveHint`/
`openWorldHint`/`idempotentHint` (`server.py`, `_RO_ANNOTATIONS` / `_LOCAL_MUTATION_ANNOTATIONS`).
13 of 14 are pure reads (`readOnlyHint: true`); `refresh` is the one exception (`readOnlyHint:
false` — it mutates our own cache, nothing destructive or external). Verified by actually calling
`list_tools()` and printing the resulting annotation on every tool, not just by reading the code.

**2. structuredContent size audit — done, using real data.** Ran every widget-producing and
data tool against the project's own live ManageBac account (18 real classes) and measured actual
byte sizes, not estimates. Two real, previously-undetected problems came out of it:

- `get_task_detail` was shipping **7,135 bytes** of `structuredContent` for a single ordinary
  task — already over the ~4-5KB widget ceiling with zero batching involved. Root cause: the
  tight `_widget_sc()` slimmer this file used to reference was dead code (never called); the
  function actually wired in, `_detail_sc()`, capped `description`/`teacher_comment` far more
  loosely (4000/2500 chars) and didn't cap `discussions`, `desc_files`, or `submitted_files` **at
  all**. Fixed: caps tightened to 1200/800 chars, and the three uncapped fields now cap at
  5/10/10 respectively (discussion bodies also capped to 400 chars each). Re-measured on the same
  real task: **4,174 bytes** — the one remaining large real-world case (a task with 10 prior
  submissions) still fits with margin; a typical task is well under that.
- `get_grades()` with no `class_id` (the "how am I doing overall" case — arguably the single most
  important query this project exists for) was at **4,655 bytes** on this 18-class test account,
  i.e. already at the edge of silently failing to render for real students. Root cause: the
  per-class payload included `best`/`average`/`out_of`/`count` for every criterion, none of which
  `widget-preview/grades-card.html` actually reads (confirmed by grep — the widget only ever
  touches `criteria[letter].latest`). Fixed: the widget-facing summary now sends only `latest`
  per criterion; the full breakdown (`best`/`average`/`out_of`/`count`) still goes to the model
  via the ordinary `content` JSON, it's just no longer duplicated into the widget-only payload.
  Re-measured: **1,951 bytes** — 58% smaller, large headroom even for bigger schools.

Both fixes verified against `tests/test_parsers.py` (still 20/20 passing) and by re-running the
same live-account measurement script before/after.

**Not hard-capped, flagged as informational risk instead:** `get_tasks` batched across all
classes measured **64,493 bytes** on the same account (18 classes × up to 12 tasks each, per the
existing `_slim_tasks`/`_TASKS_PER_CLASS_CAP` design). This tool has no attached widget, so it's
not at risk of a silent drop — the cost here is pure model context-window bloat, and the tool's
own description already tells the model not to do this ("do NOT batch every class here — that
floods the context; use get_upcoming/get_grades/tag_search instead"). That's a soft,
prompt-level guardrail, not a hard one — a model that ignores the instruction can still trigger a
60KB+ call. Left alone deliberately rather than adding an arbitrary hard cap, since truncating a
genuine "show me everything across every class" request could just as easily read as broken.
Worth a real decision (hard cap vs. leave as a documented risk) rather than a silent fix.
`get_units` (17KB for one class) and `tag_search` (15KB searching "Summative" across all classes)
are similarly large but inherent to the data (full IB unit framework text; a genuinely broad
search) — flagged, not touched, since aggressively trimming either risks cutting content the
model actually needs to help the student.

**3. Decoupled data/render tool split — reasoned through, deliberately deferred.** §3's
recommended pattern (split each combined tool into a data tool + a render tool) is real and
would be the correct long-term shape, but doing it *now*, before any widget actually calls back
into the server via `callTool`, buys nothing yet — the pattern's entire value (avoiding
unnecessary re-renders during multi-step model reasoning, letting a widget button call a data
tool directly without remounting) only shows up once there's real widget-initiated interactivity
to attach it to, which is exactly the deferred item in §19 point 2. Splitting now means either
redoing it once the redesign clarifies real interaction needs, or guessing wrong and redoing it
twice. Correct sequencing: rebuild `task-card.html` against the `ui/*` bridge first (§19 point 2,
still pending — that's a design-adjacent task, not a backend one), and decide the data/render
split as part of that same effort once the actual button-to-tool-call shape is known.

### Update — same session, after a Codex review round

Handed the diff to Codex for a second opinion (see the review prompt in the commit history /
conversation). It caught two real issues the first pass missed:

1. **`find_task` had the same widget-drop exposure `get_task_detail` did, un-fixed.** Both
   handlers build the same task-card shape via `_build_task_obj()`, but only `get_task_detail`'s
   copy got tightened — `find_task` still had the old, looser 4000/2500-char caps and zero caps
   on `discussions`/`desc_files`/`submitted_files`. Fixed by extracting the capping logic into
   one shared `_cap_task_widget_sc()` helper (`server.py`, right before `_build_task_obj`) and
   calling it from both places — same fix, can't drift apart again.
2. **Naive `text[:limit]` truncation on `description` could corrupt HTML.** `description` is
   HTML (converted from Markdown before capping), and the widget injects it via `innerHTML`
   (`task-card.html`) — slicing at an arbitrary character count can land mid-tag or mid-entity
   and produce broken markup. Fixed with `_HtmlTruncator`, a small `HTMLParser` subclass that
   streams the HTML, stops after N *visible* characters, and closes any tags still open at the
   cutoff — output is always valid regardless of where the cut lands. Verified directly: cutting
   the same HTML string at 10/25/40/60/100 characters all produced balanced, unbroken markup.
   `sc["description_truncated"]` is now also set on the payload (`true`/`false`) so a future
   widget UI can show an honest "this is a preview" state instead of implying "Show More" always
   has more to actually show.

Codex separately confirmed: the annotation choices were correct for the then-current tool set
(including `refresh`); the dropped grade fields
(`best`/`average`/`out_of`/`count`) are genuinely unused by `grades-card.html`, confirmed by its
own read of the widget source; and the decision to defer the data/render tool split is sound for
the stated reason — the combined shape's real downside (data tools having to budget for widget
payload size too) already exists today and doesn't get worse by waiting, whereas splitting
without a widget that actually calls back adds tool surface for no immediate benefit.

Re-verified end to end after this round: `tests/test_parsers.py` 20/20 passing,
`find_task`/`get_task_detail` re-measured against the same live account (708B and 4.5KB
respectively, both safely under the ~4-5KB ceiling).

### Still open
- **Widget interactivity pass** — pick one widget (task-card is highest-traffic) to rebuild
  against the `ui/*` bridge with real `callTool` wiring, `setWidgetState`, and
  `notifyIntrinsicHeight`; bundle the data/render tool split into this same effort per the
  reasoning above.
- **Clickable task navigation** — task rows/cards should have a clear hover/focus affordance and
  should open the specific task when clicked. In the preview harness this can point at the
  task's `url`, but in the real ChatGPT app this should be wired during the widget interactivity
  pass so a task-list click can open/render the task detail view directly instead of only acting
  like static text. Decide then whether the click should call `get_task_detail`, a future
  render-only task-detail tool, or `openExternal` to ManageBac depending on the final Apps SDK
  bridge shape.
- **Attachment-to-ChatGPT handoff** — desired UX: a student can click a task-card attachment and
  ask ChatGPT to use that file without manually downloading/re-uploading it. Current research
  direction from the Apps SDK docs:
  - Accepted direction: treat this as "select ManageBac attachments, then ask ChatGPT about the
    selected files and current task", not as "force the attachment into the normal ChatGPT
    composer upload UI". The task-card preview has the first-pass UI for this: selectable file
    rows, a separate open-file affordance, selected count, clear action, and "Ask ChatGPT".
  - Preferred UX is multi-select: attachment rows can be selected inside the task-card/grade
    widget, then the student can send a normal prompt such as "look at these attachments with this
    task" or click an "Ask ChatGPT about selected" action. ChatGPT should receive the task context
    plus the selected attachments' readable content without the user manually downloading or
    re-uploading files.
  - Widgets have file helpers (`window.openai.uploadFile`, `selectFiles`, `getFileDownloadUrl`),
    but those are for user-selected/uploaded ChatGPT files or file refs already authorized to the
    app. They are not, by themselves, a reliable way to turn a ManageBac signed/authenticated
    attachment URL into a composer attachment.
  - Tools can accept ChatGPT file inputs via `_meta["openai/fileParams"]`, but that solves the
    inverse case: ChatGPT/user passes a file to a tool.
  - For ManageBac attachments, the preferred implementation is widget selection ->
    a dedicated attachment-preparation path (for example `prepare_attachments_for_chatgpt`,
    batched) -> `sendFollowUpMessage` asking ChatGPT to analyze the selected files with the
    current task context. Do not expose a general `get_file_content` command to the model.
    If we later need true file handles instead of
    extracted text/image content, research whether MCP tool file references can be returned by this
    Python SDK/server stack and then consumed with `getFileDownloadUrl`.
  - UX should separate "open/download attachment" from "ask ChatGPT about this attachment", and
    the tool should stay read-only, avoid leaking raw signed URLs where possible, enforce file size
    limits, and clearly report unsupported file types.
- **Selection context handoff** — selected classes/files/attachments should not be visual-only.
  In the real widget pass, selection changes need to update model-visible context via the standard
  `ui/update-model-context` path (or whatever final ChatGPT bridge equivalent is current), so a
  later typed user prompt like "make a study plan for the selected classes" can resolve the
  selected items without requiring the user to click the widget's "Ask ChatGPT" button. Keep the
  button anyway as a fast explicit action, but do not make it the only way selection reaches the
  model.
- **`get_tasks` all-class-batch guardrail** — decide whether to add a hard cap or leave it as a
  documented, description-level-only guardrail.
- **Git branching for the visual redesign** — done; work is happening on `design-refresh`,
  branched off `multi-user`.
