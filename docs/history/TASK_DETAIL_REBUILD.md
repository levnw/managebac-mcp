# Task detail rebuild — 2026-09-17

## Evidence and scope

Reviewed the remote `multi-user` branch at commit `c41363d325a65e652740491a8083619f41546f03`, specifically `managebac_mcp/scraper.py` task detail parsing/fetching. Source was retrieved directly from GitHub; the old implementation was not imported or copied.

The old parser recognized `.page-title` on any element and then generic h1/h2 headings; V2 originally accepted only four specific heading selectors. V2 also chose the first arbitrary data-task-id container, which could exclude the actual heading. These are credible explanations for the observed title error, not proof of the current live DOM layout.

## New implementation

`sources/managebac/task_detail.py` owns task detail parsing. `tasks.py` owns list parsing, with a compatibility import for callers of the previous detail function. `tools/task.py` still fetches exactly one page and passes it to the detail adapter.

- Use the main page region rather than an arbitrary task-ID-bearing control.
- Validate canonical/page-container identity when supplied.
- Resolve section boundaries independently from the title.
- Prefer explicit page/task titles; otherwise accept a unique meaningful h1/h2 outside instructions, resources, navigation and other task sections. Ambiguity fails instead of choosing the first candidate.
- Support a heading-only wrapper before a section's content. Multiple distinct matching sections fail visibly.
- Preserve the complete description container, including content before/after editor wrappers, through the ordered rich-text parser.
- Keep task metadata out of instructions/resource/feedback content; do not infer status from their badges.
- Keep teacher resources, submissions, feedback, assessment and history distinct. Missing sections remain `not_on_page`.
- Remove extracted author/title/date labels from the same resource's content tree to avoid duplicate representations.
- Keep feedback preview references distinct from downloads; omit opaque viewer values and meaningless `href="#"` controls.
- Keep rich assets as references, not claims that their binary contents were read.
- No automatic discussions, login, attachment downloads, caching or widget work.

Safe developer events indicate title recognition/candidate counts and recognized section counts; raw HTML and credentials are not added to diagnostics. Existing error-report files remain unchanged.

## Verification and remaining gate

85 tests pass, including the original rich content, single-request, MCP and error tests plus historical layout variants, ambiguity, metadata separation, preview handling and description sibling preservation.

These new layouts are synthetic regression fixtures based on historical source evidence. No authenticated task page was captured during this rebuild. A fresh live Get selected task call is still required before claiming that the user's failing page is fixed. Alternate title placement outside main, different section boundaries or additional task types may require more real evidence.

Only Working/local preview is updated. Approved and the public connector are unchanged. The task-list count warning and class-files upstream error are separate issues and were not changed here.
