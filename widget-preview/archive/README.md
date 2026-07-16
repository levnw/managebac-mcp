# Archived widgets — pre-redesign (2026-07-16)

These are the ManageBac-pixel-matched widgets that were live in production up to the
`pre-redesign-2026-07-16` tag. They are **kept for reference, not served** — the redesign
(ChatGPT-native style, per the design brief and OpenAI's Apps SDK UI guidelines) replaces the
same-named files in the parent directory.

Also recoverable any time via `git checkout pre-redesign-2026-07-16 -- widget-preview/`.

## What the old task card contained (feature inventory, so nothing gets lost silently)

Data contract (unchanged — the new widgets read the same `structuredContent` shape, built by
`_build_task_obj()` + `_cap_task_widget_sc()` in `server.py`):

- `title`, `class_name`, `url`
- `due_month`, `due_day`, `due_past`, `due_time`, `due_passed_late`
- `labels` [{text, style}] — label-summative / label-formative / label-homework / label-classwork
- `status` — Submitted | Not Submitted | Pending | Complete | Incomplete | Not Assessed Yet | N/A
- `grades` [{label, score, max}] | null
- `teacher_comment` string | null
- `unit` {name, url, color, start_label, progress, duration} | null
- `description` HTML string | null, plus `description_truncated` bool
- `desc_files` [{name, size, url}] — files embedded in the description
- `resources` [{author, posted, label, files[{name, size, url}]}] — teacher-posted file groups
- `submitted_files` [{name, uploaded, url}] | null — null = NO dropbox, [] = dropbox but empty
- `discussions` [{author, body, posted}] | null — null = hide, [] = show empty state
- `images` [urls] — teacher-embedded description images
- `theme_color` — per-school ManageBac theme (ignored by the redesign; native style instead)

Old visual features not carried into the redesigned inline card (by design-brief decision —
available for a future fullscreen view instead): the blue ManageBac header bar, the full
dropbox table with Turnitin column and GDrive/Upload buttons, full resource groups with author
avatars and ManageBac icon assets (`managebac-icons/`), the unit progress card with color bar,
discussions section with empty-state art, teacher-embedded description images.
