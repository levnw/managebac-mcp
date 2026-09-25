# Shared developer-mode diagnostics

Updated 2026-09-13: shared diagnostics and automatic login/get_classes exports are implemented.

## Automatic developer exports

Operator setting: `MBV2_DEVELOPER_MODE=1` when starting the process. Default OFF.
Login and get_classes use the same ReportWriter in diagnostics.py. When OFF, no
report directory or files are created. Browser controls cannot enable it.

Default server location: `/Users/server/Desktop/ManageBac-V2/Working/Test Reports/`.
MBV2_REPORT_DIR overrides the report location independently of account storage.
Tests that inject a state directory keep reports inside their temporary directory.
Each run has its own timestamp-operation-random folder containing:

- response.json: exact get_classes application JSON (classes only on success;
  error only on failure), without the MCP protocol envelope or duplicated text,
  or the safe login result (authenticated, verification, error). Login is
  not an MCP tool. No session credentials are included.
- report.json: safe stage diagnostics; class runs also include the tool definition,
  response and serialized byte count. This file is not sent to the model.

The existing developer report viewer (/api/reports, same authenticated workbench
session) shows export paths or an explicit export failure. A disk failure does not
break login or change the tool result. Academic data is private: directories are
0700, files 0600, ignored by Git, and not served as public static files.
Exports persist after restart. Maximum 1,000 run folders and 2 MB per run; at the
limit saving fails visibly instead of deleting old evidence. No automatic cleanup.
A failed write can leave a partial folder; check saved status before relying on it.

This is not an academic cache: no such cache is currently implemented. Normal
account storage and in-memory session handling are unchanged. Reports from earlier
runs cannot be recovered; enable the setting and perform a fresh operation.
School discovery still uses temporary, bounded diagnostics only.

Every implemented component should support the same diagnostic mechanism: school discovery, authentication, transport, each retrieval capability, result formatting and eventual readiness orchestration. Do not duplicate separate debug systems across tools.

- Developer mode is OFF by default. Ordinary responses retain essential error, completeness and freshness information, but do not include detailed diagnostic reports.
- When explicitly enabled by the developer/operator, collect bounded diagnostic events and make the report available on demand. Do not automatically append debug data to every model-facing response.
- Use a shared request/report identifier to relate stages. Useful events include stage name, safe route name, duration, page number, record counts, validation outcomes and sanitized failures. Enable source-to-extraction-to-output comparison where safe.
- Never record passwords, cookies, authorization headers, OAuth tokens, CSRF values or signed download links, even in developer mode. Never dump raw request/response bodies indiscriminately.
- Academic records remain private: expose requested diagnostic records only to the authorized account/operator, and label any redacted output. Automatic disk export is explicitly enabled by the operator as described above.
- Enforce report access and developer-mode control on the server. A browser toggle alone must not grant privileged access or cross-account visibility.
- Reports must distinguish directly observed source facts from derived fields and actual outgoing tool payloads. Debug mode must not change extraction semantics or turn unverified data into success.
- A report that was not collected while developer mode was off cannot be recovered retroactively. Explain when a fresh run is needed.

Future retrieval capabilities should reuse this mechanism; unimplemented capabilities are not instrumented yet.
