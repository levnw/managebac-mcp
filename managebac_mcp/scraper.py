"""
All HTML parsing logic. Each fetch_* function takes raw HTML (str) so it can
be unit-tested with fixture files without hitting the network.
The fetch_*_live wrappers handle HTTP + cache.
"""
import re
from typing import Any
from bs4 import BeautifulSoup, Tag

from . import cache
from .auth import authed_get, get_client, login
from .config import BASE_URL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _text(el: Tag | None) -> str:
    return el.get_text(strip=True) if el else ""


def _html_to_markdown(el) -> str:
    """
    Convert a BeautifulSoup element to Markdown, preserving rich formatting.

    ManageBac uses inline styles rather than semantic tags:
      style="font-weight: bold"    → **bold**
      style="font-style: italic"   → *italic*
      style="text-decoration: underline" → __underline__ (shown as bold too)
    Standard tags (strong, em, h1-h6, ul, ol, a, br) are also handled.
    """
    from bs4 import NavigableString

    def node(el) -> str:
        if isinstance(el, NavigableString):
            return str(el)

        tag = getattr(el, "name", None)
        if tag is None:
            return ""

        style = el.get("style", "")
        bold = ("font-weight: bold" in style or "font-weight:bold" in style
                or tag in ("strong", "b"))
        italic = ("font-style: italic" in style or "font-style:italic" in style
                  or tag in ("em", "i"))

        def kids() -> str:
            return "".join(node(c) for c in el.children)

        # --- block elements ---
        if tag == "br":
            return "\n"
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            return "#" * int(tag[1]) + " " + kids().strip() + "\n\n"
        if tag == "p":
            t = kids().strip()
            return (t + "\n\n") if t else ""
        if tag in ("div", "section"):
            t = kids().strip()
            return (t + "\n\n") if t else ""
        if tag == "ul":
            items = ["- " + "".join(node(c) for c in li.children).strip()
                     for li in el.find_all("li", recursive=False)]
            return ("\n".join(items) + "\n\n") if items else ""
        if tag == "ol":
            items = [f"{i}. " + "".join(node(c) for c in li.children).strip()
                     for i, li in enumerate(el.find_all("li", recursive=False), 1)]
            return ("\n".join(items) + "\n\n") if items else ""
        if tag == "li":
            return "- " + kids().strip() + "\n"

        # --- inline elements ---
        if tag == "a":
            href = el.get("href", "")
            a_classes = el.get("class", [])
            # Embedded file attachment — render as a plain label, not a link
            # (the URL is captured separately in embedded_files)
            if "fr-file" in a_classes or el.get("data-name"):
                name = el.get("data-name") or ""
                size_el = el.find(class_="fr-file-size")
                size = size_el.get_text(strip=True) if size_el else ""
                label = name or el.get_text(strip=True)
                return f"📎 {label}" + (f" ({size})" if size else "")
            text = kids().strip()
            if href.startswith("http"):
                label = text if (text and text != href) else href
                return f"[{label}]({href})"
            return kids()

        if tag in ("span", "strong", "b", "em", "i", "u"):
            text = kids()
            stripped = text.strip()
            if not stripped:
                return text
            if bold and italic:
                return text.replace(stripped, f"***{stripped}***", 1)
            elif bold:
                return text.replace(stripped, f"**{stripped}**", 1)
            elif italic:
                return text.replace(stripped, f"*{stripped}*", 1)
            return text

        # everything else — just recurse
        return kids()

    md = node(el)
    md = re.sub(r'\n{3,}', '\n\n', md)   # collapse 3+ blank lines → 2
    md = re.sub(r' +\n', '\n', md)        # strip trailing spaces
    return md.strip()


def _parse_grade_box(cell: Tag) -> dict[str, dict]:
    """Parse grade cells like B: [7|8] C: [5|8] into {B: {score:7, max:8}}"""
    grades = {}
    # Each criterion label + score box pair
    labels = cell.find_all(string=re.compile(r'^[A-D]:$'))
    for label in labels:
        label_text = label.strip().rstrip(":")
        # Score boxes are siblings: two consecutive elements with numbers
        boxes = []
        sibling = label.parent.next_sibling if label.parent else None
        # Walk siblings looking for score boxes
        for _ in range(6):
            if sibling is None:
                break
            if hasattr(sibling, 'get_text'):
                t = sibling.get_text(strip=True)
                if re.match(r'^\d+$', t):
                    boxes.append(int(t))
                elif t and t not in (':', '|'):
                    if boxes:
                        break
            sibling = getattr(sibling, 'next_sibling', None)
        if len(boxes) >= 2:
            grades[label_text] = {"score": boxes[0], "max": boxes[1]}
        elif len(boxes) == 1:
            grades[label_text] = {"score": boxes[0], "max": None}
    return grades


def _parse_grades_from_task_row(row: Tag) -> dict[str, dict]:
    """
    Parse grades from the right-side grade column of a task row.
    Handles formats like: A: [7|8]  or  B: [7|8] C: [5|8]  or  N/A
    """
    grades = {}
    # Find the grade column — it's the last cell / div in the row
    grade_col = row.find(class_=re.compile(r'grade|criterion|score', re.I))
    if not grade_col:
        # Try to find by position — look for elements with number boxes
        all_divs = row.find_all("div")
        for div in reversed(all_divs):
            text = div.get_text()
            if re.search(r'[A-D]:\s*\d', text):
                grade_col = div
                break

    if not grade_col:
        return grades

    text = grade_col.get_text(" ", strip=True)
    # Pattern: "A: 7 8" or "B: 7 8 C: 5 8"
    for match in re.finditer(r'([A-D]):\s*(\d+)\s+(\d+)', text):
        criterion, score, max_score = match.groups()
        grades[criterion] = {"score": int(score), "max": int(max_score)}

    return grades


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------

def parse_classes(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    classes = []

    # Each class entry is a link in the left sidebar or class list
    # URL pattern: /student/classes/{id}
    for a in soup.find_all("a", href=re.compile(r'/student/classes/\d+$')):
        href = a["href"]
        class_id = re.search(r'/classes/(\d+)', href).group(1)
        name = a.get_text(strip=True)
        if not name or name in ("Browse All Classes", "Classes"):
            continue

        # Detect level tags (HL/SL) near this element
        parent = a.parent
        tags = [t.get_text(strip=True) for t in parent.find_all(
            class_=re.compile(r'tag|label|badge', re.I))] if parent else []

        classes.append({
            "id": class_id,
            "name": name,
            "url": f"{BASE_URL}/student/classes/{class_id}",
            "level_tags": tags,
        })

    # Deduplicate by id (sidebar + main list may repeat)
    seen = set()
    unique = []
    for c in classes:
        if c["id"] not in seen:
            seen.add(c["id"])
            unique.append(c)
    return unique


async def fetch_classes() -> list[dict]:
    cached = cache.get("get_classes")
    if cached is not None:
        return cached

    async with await get_client() as client:
        r = await authed_get(client, "/student/classes/my")
        if "/login" in str(r.url):
            await login(client)
            r = await authed_get(client, "/student/classes/my")

    result = parse_classes(r.text)

    # For each class, check if it has a journal tab
    async with await get_client() as client:
        for cls in result:
            r2 = await authed_get(client, f"/student/classes/{cls['id']}")
            cls["has_journal"] = "learner_portfolio" in r2.text

    cache.set("get_classes", result, "get_classes")
    return result


# ---------------------------------------------------------------------------
# Timetable
# ---------------------------------------------------------------------------

def parse_timetable(html: str) -> list[dict]:
    """
    Parse the weekly timetable from table.f-timetable.

    Structure:
      thead > tr > th[0]="Period" th[1]="Jun 1, Mon" ... th[5]="Jun 5, Fri"
      tbody > tr (one per period):
        th > span.f-numeric      → period number  (or small text for "Homeroom")
        td (one per day):
          a.f-timetable-item     → one class per cell (sometimes multiple)
            div.f-box-item__body:
              small.color-secondary    → "9:00 AM - 9:45 AM"
              div.badge.tasks-counter  → optional task count badge
                span.badge-label       → "1"
              p.fw-semibold.text-truncate → class name
              p.text-truncate.mt-1    → grade (skip)
              p.text-truncate         → teacher name
              p.text-truncate         → room number (optional)
            data-bs-content-url has ib_class_id=12734184 for class_id
    """
    soup = BeautifulSoup(html, "lxml")
    slots = []

    table = soup.find("table", class_="f-timetable")
    if not table:
        return slots

    # Day names from header row
    thead = table.find("thead")
    days = []
    if thead:
        for th in thead.find_all("th")[1:]:  # skip "Period" column
            days.append(th.get_text(strip=True))

    tbody = table.find("tbody")
    if not tbody:
        return slots

    for row in tbody.find_all("tr"):
        # Period number — span.f-numeric for numbered periods, small for named (Homeroom)
        row_th = row.find("th")
        if not row_th:
            continue
        numeric_el = row_th.find("span", class_="f-numeric")
        if numeric_el:
            period_text = numeric_el.get_text(strip=True)
            try:
                period = int(period_text)
            except ValueError:
                continue
            period_name = str(period)
        else:
            period_name = row_th.get_text(strip=True)
            period = 0  # Homeroom / special rows

        for i, cell in enumerate(row.find_all("td")):
            day = days[i] if i < len(days) else f"Day{i+1}"

            # Each class in this cell is an a.f-timetable-item
            for item in cell.find_all("a", class_="f-timetable-item"):
                body = item.find("div", class_="f-box-item__body")
                if not body:
                    continue

                # Time
                time_el = body.find("small", class_="color-secondary")
                time_text = time_el.get_text(strip=True) if time_el else ""
                times = re.findall(r'\d+:\d+\s*[AP]M', time_text)

                # Task count
                badge_label = body.find("span", class_="badge-label")
                task_count = 0
                if badge_label:
                    try:
                        task_count = int(badge_label.get_text(strip=True))
                    except ValueError:
                        pass

                # Class name, teacher, room — the <p> elements in order:
                # p.fw-semibold = class name, p.mt-1 = grade (skip), remaining p = teacher, room
                paragraphs = body.find_all("p")
                class_name = ""
                teacher = ""
                room = ""
                content_ps = []
                for p in paragraphs:
                    p_classes = p.get("class", [])
                    if "fw-semibold" in p_classes:
                        class_name = p.get_text(strip=True)
                    elif "mt-1" not in p_classes:
                        content_ps.append(p.get_text(strip=True))
                if content_ps:
                    teacher = content_ps[0]
                if len(content_ps) > 1:
                    room = content_ps[1]

                # Class ID from URL param
                content_url = item.get("data-bs-content-url", "")
                class_id_match = re.search(r'ib_class_id=(\d+)', content_url)
                class_id = class_id_match.group(1) if class_id_match else ""

                if class_name:
                    slots.append({
                        "period": period if period else period_name,
                        "day": day,
                        "time_start": times[0] if times else "",
                        "time_end": times[1] if len(times) > 1 else "",
                        "class_name": class_name,
                        "class_id": class_id,
                        "teacher": teacher,
                        "room": room,
                        "task_count": task_count,
                    })

    return slots


async def fetch_timetable() -> list[dict]:
    cached = cache.get("get_timetable")
    if cached is not None:
        return cached

    async with await get_client() as client:
        r = await authed_get(client, "/student/timetables")

    result = parse_timetable(r.text)
    cache.set("get_timetable", result, "get_timetable")
    return result


# ---------------------------------------------------------------------------
# Tasks list
# ---------------------------------------------------------------------------

def parse_tasks(html: str, class_id: str = "") -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    tasks = []

    # Task rows use class "fusion-card-item" — each contains one task link + optional comment
    rows = soup.find_all(class_="fusion-card-item")
    for row in rows:
        # Find the task title link
        a = row.find("a", href=re.compile(r'/core_tasks/\d+'))
        if not a:
            continue
        href = a["href"]
        task_id_match = re.search(r'/core_tasks/(\d+)', href)
        if not task_id_match:
            continue
        task_id = task_id_match.group(1)
        title = a.get_text(strip=True)
        if not title or title in ("Submit Coursework", "View Teacher Feedback"):
            continue

        row_text = row.get_text(" ", strip=True)

        # Date — month + day
        date_match = re.search(
            r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+(\d{1,2})',
            row_text, re.I
        )
        date_str = f"{date_match.group(1)} {date_match.group(2)}" if date_match else ""

        # Due day/time
        due_match = re.search(
            r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+at\s+\d+:\d+\s*[AP]M',
            row_text, re.I
        )
        due_day_time = due_match.group(0) if due_match else ""

        # Tags — label spans
        # ManageBac uses badge/label/tag elements but many of them contain dates, status
        # words, grade numbers, or long concatenations — filter those out aggressively.
        _JUNK_TAG = re.compile(
            r'^\d+$'                                                             # pure numbers (grade scores)
            r'|^[A-Z][a-z]{2}\d{1,2}$'                                          # dates like "Mar31", "Jun2"
            r'|(Summative|Formative|Pending|Submitted|Complete|Incomplete|Not\s+Submitted|N/A)'
            r'|at\s+\d+:\d+'                                                     # contains a time
            , re.I
        )
        tags = []
        for tag_el in row.find_all(class_=re.compile(r'\btag\b|\bbadge\b|\blabel\b', re.I)):
            t = tag_el.get_text(strip=True)
            if t and len(t) <= 40 and not _JUNK_TAG.search(t):
                tags.append(t)

        task_type = "Summative" if "Summative" in row_text else "Formative" if "Formative" in row_text else ""
        criterion_tags = list(dict.fromkeys(tags))  # deduplicate, preserve order

        # Status
        status = "Pending"
        for s in ("Submitted", "Complete", "Not Submitted", "Not Assessed Yet", "Incomplete", "Pending"):
            if s in row_text:
                status = s
                break
        if "N/A" in row_text and not any(x in row_text for x in ("Submitted", "Pending", "Incomplete")):
            status = "N/A"

        has_submission_box = bool(row.find(string=re.compile(r'Submit Coursework', re.I)))

        # Grades — pattern "A: 7 8"
        grades = {}
        for match in re.finditer(r'\b([A-D]):\s*(\d+)\s+(\d+)', row_text):
            criterion, score, max_score = match.groups()
            grades[criterion] = {"score": int(score), "max": int(max_score)}

        # Teacher comment — inside div.assessment-comments > div.show-more > div.fix-body-margins
        comment = ""
        comment_block = row.find(class_="assessment-comments")
        if comment_block:
            content_div = comment_block.find(class_=re.compile(r'fix-body-margins|fr-element|rte', re.I))
            if content_div:
                comment = _html_to_markdown(content_div)
            else:
                comment = comment_block.get_text(" ", strip=True)

        tasks.append({
            "id": task_id,
            "title": title,
            "url": f"{BASE_URL}/student/classes/{class_id}/core_tasks/{task_id}" if class_id else "",
            "date": date_str,
            "due_day_time": due_day_time,
            "type": task_type,
            "tags": criterion_tags,
            "status": status,
            "has_submission_box": has_submission_box,
            "grades": grades,
            "teacher_comment": comment,
        })

    return tasks


async def fetch_tasks(class_id: str) -> list[dict]:
    cache_key = f"get_tasks:{class_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    async with await get_client() as client:
        r = await authed_get(client, f"/student/classes/{class_id}/core_tasks")

    result = parse_tasks(r.text, class_id)
    cache.set(cache_key, result, "get_tasks")
    return result


# ---------------------------------------------------------------------------
# Task detail
# ---------------------------------------------------------------------------

def parse_task_detail(html: str, class_id: str, task_id: str) -> dict:
    soup = BeautifulSoup(html, "lxml")

    # Description block — find <h4>Description</h4> then get next sibling div.show-more
    # Inside that: div.fix-body-margins (the actual content)
    desc_heading = soup.find(["h4", "h3", "h2"], string=re.compile(r'^Description$', re.I))
    desc_block = None
    if desc_heading:
        sib = desc_heading.find_next_sibling()
        if sib:
            # May be div.show-more or directly the content div
            inner = sib.find(class_=re.compile(r'fix-body-margins|fr-element', re.I))
            desc_block = inner if inner else sib

    desc_text = ""
    desc_links = []
    desc_files = []

    if desc_block:
        desc_text = _html_to_markdown(desc_block)

        for a in desc_block.find_all("a", href=True):
            href = a.get("href", "")
            a_classes = a.get("class", [])

            # Embedded file — ManageBac uses <a class="fr-file" data-name="...">
            if "fr-file" in a_classes or a.get("data-name"):
                name = a.get("data-name") or a.get_text(strip=True)
                size_el = a.find(class_="fr-file-size")
                size = size_el.get_text(strip=True) if size_el else ""
                if name:
                    desc_files.append({"name": name, "size": size, "url": href})

            # External link (Google Docs, YouTube, etc.)
            elif href.startswith("http") and "managebac.com" not in href:
                text = a.get_text(strip=True)
                # Use the href as text if the anchor text is just the URL itself
                desc_links.append({"text": text if text != href else href, "url": href})

        # Also catch bare URLs typed as plain text (not wrapped in <a>)
        _URL_RE = re.compile(r'https?://[^\s<>"\']+')
        linked_urls = {d["url"] for d in desc_links}
        for text_node in desc_block.find_all(string=_URL_RE):
            # Skip if inside an <a> tag (already captured above)
            if text_node.parent and text_node.parent.name == "a":
                continue
            for url in _URL_RE.findall(str(text_node)):
                if url not in linked_urls and "managebac.com" not in url:
                    desc_links.append({"text": url, "url": url})
                    linked_urls.add(url)

    # Resources section (teacher-posted files on the task)
    resources = []
    resources_section = soup.find(string=re.compile(r'^Resources$', re.I))
    if resources_section:
        resources_container = resources_section.find_parent()
        while resources_container and not resources_container.find_all(class_=re.compile(r'file|attachment', re.I)):
            resources_container = resources_container.find_parent()
        if resources_container:
            for post in resources_container.find_all(class_=re.compile(r'post|entry|item', re.I)):
                teacher_el = post.find(class_=re.compile(r'author|name|user', re.I))
                teacher = teacher_el.get_text(strip=True) if teacher_el else ""
                label_el = post.find(["p", "strong", "b"])
                label = label_el.get_text(strip=True) if label_el else ""
                files = []
                for f in post.find_all(class_=re.compile(r'file|attachment', re.I)):
                    fname = f.find("a")
                    fsize = f.find(string=re.compile(r'\d+\s*(KB|MB)', re.I))
                    files.append({
                        "name": fname.get_text(strip=True) if fname else "",
                        "size": str(fsize).strip() if fsize else "",
                    })
                if teacher or files:
                    resources.append({"teacher": teacher, "label": label, "files": files})

    # Dropbox / submitted files — each is a <tr class="file"> inside the dropbox table
    submitted_files = []
    for tr in soup.find_all("tr", class_="file"):
        # Filename — in <a class="text-break"> or <div class="details"> > <a>
        file_link = tr.find("a", class_="text-break") or tr.find(class_="details", recursive=True)
        if file_link and file_link.name != "a":
            file_link = file_link.find("a")
        fname = file_link.get_text(strip=True) if file_link else ""
        if not fname:
            continue

        # Upload timestamp — in a <label> inside the row
        uploaded_at = ""
        label = tr.find("label")
        if label:
            t = label.get_text(strip=True)
            up_match = re.search(r'Uploaded (.+)', t)
            if up_match:
                uploaded_at = up_match.group(1)

        # Teacher feedback token
        feedback_btn = tr.find("a", attrs={"data-pdf-preview-url-value": True})
        feedback_token = feedback_btn["data-pdf-preview-url-value"] if feedback_btn else None

        submitted_files.append({
            "name": fname,
            "uploaded_at": uploaded_at,
            "teacher_feedback_token": feedback_token,
        })

    # Task history from sidebar
    history = {}
    history_section = soup.find(string=re.compile(r'Task History', re.I))
    if history_section:
        history_container = history_section.find_parent()
        text = history_container.get_text(" ", strip=True) if history_container else ""
        created = re.search(r'Created (.+?)(?:Reminder|Last Updated|$)', text)
        reminder = re.search(r'Reminder Sent (.+?)(?:Last Updated|$)', text)
        updated = re.search(r'Last Updated (.+?)$', text)
        if created:
            history["created_at"] = created.group(1).strip()
        if reminder:
            history["reminder_sent_at"] = reminder.group(1).strip()
        if updated:
            history["last_updated_at"] = updated.group(1).strip()

    return {
        "class_id": class_id,
        "task_id": task_id,
        "url": f"{BASE_URL}/student/classes/{class_id}/core_tasks/{task_id}",
        "description": {
            "text": desc_text,
            "links": desc_links,
            "embedded_files": desc_files,
        },
        "resources": resources,
        "submitted_files": submitted_files,
        "task_history": history,
    }


def parse_discussions(html: str, class_id: str, task_id: str) -> list[dict]:
    """
    Parse discussion posts from /core_tasks/{id}/discussions.

    Each post is a div.discussion containing:
      div.author          → poster's name
      div.date.gray-text  → "Posted on Friday, Nov 14, 2025 at 4:00 PM"
      div.body.pt-3
        div.fix-body-margins  → message text + any embedded links/files

    Replies (if any) appear as div.reply elements beneath the main post.
    """
    soup = BeautifulSoup(html, "lxml")
    posts = []

    for post in soup.find_all("div", class_="discussion"):
        post_id_attr = post.get("id", "")  # e.g. "discussion_27539214"
        post_id = post_id_attr.replace("discussion_", "")

        # Author
        author_el = post.find("div", class_="author")
        author = author_el.get_text(strip=True) if author_el else ""

        # Date — "Posted on Friday, Nov 14, 2025 at 4:00 PM"
        date_el = post.find("div", class_="date")
        date_raw = date_el.get_text(strip=True) if date_el else ""
        date = re.sub(r'^Posted on\s*', '', date_raw).strip()

        # Body — text + links
        # Use the whole div.body container so text nodes outside fix-body-margins are included
        body_div = post.find("div", class_="body")
        body_text = ""
        body_links = []
        if body_div:
            body_text = _html_to_markdown(body_div)
            for a in body_div.find_all("a", href=True):
                href = a.get("href", "")
                text = a.get_text(strip=True)
                if href.startswith("http"):
                    body_links.append({"text": text or href, "url": href})

        # Replies — div.reply elements anywhere in the post
        replies = []
        for reply in post.find_all("div", class_="reply"):
            if "form" in reply.get("class", []):
                continue  # skip the reply input form
            r_author_el = reply.find(class_=re.compile(r'author|name', re.I))
            r_author = r_author_el.get_text(strip=True) if r_author_el else ""
            r_date_el = reply.find("div", class_="date")
            r_date_raw = r_date_el.get_text(strip=True) if r_date_el else ""
            r_date = re.sub(r'^Posted on\s*', '', r_date_raw).strip()
            r_body_div = reply.find("div", class_="body")
            r_text = ""
            r_links = []
            if r_body_div:
                r_text = _html_to_markdown(r_body_div)
                for a in r_body_div.find_all("a", href=True):
                    href = a.get("href", "")
                    t = a.get_text(strip=True)
                    if href.startswith("http"):
                        r_links.append({"text": t or href, "url": href})
            if r_author or r_text:
                replies.append({
                    "author": r_author,
                    "posted_at": r_date,
                    "text": r_text,
                    "links": r_links,
                })

        if author or body_text:
            posts.append({
                "id": post_id,
                "author": author,
                "posted_at": date,
                "text": body_text,
                "links": body_links,
                "replies": replies,
            })

    return posts


async def fetch_task_detail(class_id: str, task_id: str) -> dict:
    cache_key = f"get_task_detail:{class_id}:{task_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    async with await get_client() as client:
        r = await authed_get(client, f"/student/classes/{class_id}/core_tasks/{task_id}")
        r_disc = await authed_get(client, f"/student/classes/{class_id}/core_tasks/{task_id}/discussions")

    result = parse_task_detail(r.text, class_id, task_id)
    result["discussions"] = parse_discussions(r_disc.text, class_id, task_id)
    cache.set(cache_key, result, "get_task_detail")
    return result


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def parse_files(html: str) -> list[dict]:
    import json as _json
    # lxml strips data-ec3-info attributes — use html.parser here
    soup = BeautifulSoup(html, "html.parser")
    files = []

    # Class files use <div class="row file" data-ec3-info='{...}'> elements
    # data-ec3-info JSON has: name, file_size, created_at, updated_at
    for row in soup.find_all(attrs={"data-ec3-info": True}):
        try:
            info = _json.loads(row["data-ec3-info"])
        except Exception:
            continue
        name = info.get("name", "")
        if not name:
            continue

        file_size_bytes = info.get("file_size", 0)
        if file_size_bytes:
            if file_size_bytes >= 1_048_576:
                size = f"{file_size_bytes / 1_048_576:.1f} MB"
            else:
                size = f"{file_size_bytes / 1024:.1f} KB"
        else:
            size = ""

        # Author — inside the row's author element
        author_el = row.find(class_=re.compile(r'author|uploader|user', re.I))
        if not author_el:
            author_el = row.find("a", href=re.compile(r'/users/', re.I))
        author = author_el.get_text(strip=True) if author_el else ""

        # Date and download URL from JSON
        date = info.get("updated_at", info.get("created_at", ""))
        url = info.get("download_url", "")

        files.append({
            "name": name,
            "size": size,
            "url": url,
            "uploaded_by": author,
            "uploaded_at": date,
        })

    # Fallback: <tr class="file"> rows (used in some class file views)
    if not files:
        for tr in soup.find_all("tr", class_="file"):
            name_link = tr.find("a", class_="text-break")
            if not name_link:
                continue
            name = name_link.get_text(strip=True)
            row_text = tr.get_text(" ", strip=True)
            size_match = re.search(r'(\d+(?:\.\d+)?\s*(?:KB|MB|GB))', row_text, re.I)
            size = size_match.group(1) if size_match else ""
            author_match = re.search(r'by\s+(.+?)(?:\s+\d|$)', row_text)
            author = author_match.group(1).strip() if author_match else ""
            files.append({"name": name, "size": size, "uploaded_by": author, "uploaded_at": ""})

    return files


async def fetch_files(class_id: str) -> list[dict]:
    cache_key = f"get_files:{class_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    async with await get_client() as client:
        r = await authed_get(client, f"/student/classes/{class_id}/files")

    result = parse_files(r.text)
    cache.set(cache_key, result, "get_files")
    return result


# ---------------------------------------------------------------------------
# Journal
# ---------------------------------------------------------------------------

def parse_journal(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    entries = []

    # Each journal entry is div.journal-evidence (e.g. id="evidence-58103436")
    # Structure:
    #   h4.title
    #     span.padding-right  → date "March 20, 2026"
    #     small               → time "1:33 AM"
    #     small.labels-set    → learning outcomes
    #     div.actions         → star / edit / delete links
    #       a[data-star]      → star toggle; href contains /star; if starred the SVG fill changes
    #   div.body
    #     div.fix-body-margins  → reflection text + any embedded links/files
    for entry in soup.find_all("div", class_="journal-evidence"):
        entry_id = entry.get("id", "")  # e.g. "evidence-58103436"

        # Date
        date_span = entry.find("span", class_="padding-right")
        date = date_span.get_text(strip=True) if date_span else ""
        if not date:
            continue

        # Time (optional)
        time_el = entry.find("small", class_=False)
        time_str = time_el.get_text(strip=True) if time_el else ""

        # Learning outcomes / labels — skip meta-labels like "Read-only"
        outcomes = []
        for label in entry.find_all("div", class_="label-outcome"):
            t = label.get_text(strip=True)
            if t and not re.match(r'^read.?only$', t, re.I):
                outcomes.append(t)

        # Starred — the star <a> has data-star attribute; if the path contains "/unstar"
        # or the SVG has a filled colour it's starred. Simplest signal: look for data-unstar
        # text = "Unstar" (meaning it IS currently starred, click to unstar).
        star_a = entry.find("a", attrs={"data-star": True})
        is_starred = False
        if star_a:
            # If button currently says "Unstar" → already starred
            is_starred = star_a.get("data-unstar", "").lower() == "unstar" and \
                         star_a.get("data-star", "").lower() == "star"
            # Fallback: check href — starred entries have /star in href still (toggle),
            # but we can also check the SVG fill colour
            svg = star_a.find("svg")
            if svg:
                path = svg.find("path")
                if path:
                    fill = path.get("fill", "")
                    # Filled gold/yellow star = starred; outline grey = not starred
                    is_starred = fill not in ("", "#859bbb", "none")

        is_read_only = bool(entry.find(string=re.compile(r'Read.?only', re.I)))

        # Body text and links
        body_div = entry.find("div", class_="fix-body-margins")
        body_text = _html_to_markdown(body_div) if body_div else ""

        links = []
        files = []
        if body_div:
            for a in body_div.find_all("a", href=True):
                href = a.get("href", "")
                text = a.get_text(strip=True)
                a_classes = a.get("class", [])
                if "fr-file" in a_classes or a.get("data-name"):
                    # Embedded file attachment
                    name = a.get("data-name") or text
                    size_el = a.find(class_="fr-file-size")
                    size = size_el.get_text(strip=True) if size_el else ""
                    files.append({"name": name, "size": size})
                elif href.startswith("http"):
                    links.append({"text": text or href, "url": href})

        entries.append({
            "id": entry_id.replace("evidence-", ""),
            "date": date,
            "time": time_str,
            "learning_outcomes": outcomes,
            "is_starred": is_starred,
            "is_read_only": is_read_only,
            "body": body_text,
            "links": links,
            "files": files,
        })

    return entries


async def fetch_journal(class_id: str) -> list[dict]:
    cache_key = f"get_journal:{class_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    async with await get_client() as client:
        r = await authed_get(client, f"/student/classes/{class_id}/learner_portfolio/reflections")

    # If no journal for this class — return empty
    if r.status_code == 404 or "/login" in str(r.url):
        return []
    if "learner_portfolio" not in str(r.url) and "Journal" not in r.text:
        return []

    result = parse_journal(r.text)
    cache.set(cache_key, result, "get_journal")
    return result


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

def parse_units(html: str, class_id: str) -> list[dict]:
    """
    Parse the /units page to get each unit's id, title, start date,
    duration, and current status.  IB detail fields are filled in later
    by parse_unit_popup().
    """
    soup = BeautifulSoup(html, "lxml")
    units = []

    prefix = f"ib_class_{class_id}_core_unit_"
    for div in soup.find_all("div", id=re.compile(rf"^ib_class_{class_id}_core_unit_\d+$")):
        div_id = div.get("id", "")
        unit_id = div_id.replace(prefix, "")
        if not unit_id.isdigit():
            continue

        # Skip weekly-planner duplicates
        weekly_id = f"ib_class_{class_id}_weekly_core_unit_{unit_id}"
        if soup.find("div", id=weekly_id) and div_id != weekly_id:
            pass  # keep the canonical one

        unit_comp = div.find("div", class_="unit-component")
        if not unit_comp:
            continue

        # Title
        h4 = unit_comp.find("p", class_="h4")
        title_a = h4.find("a") if h4 else None
        title = title_a.get_text(strip=True) if title_a else ""
        if not title:
            continue

        # Start date — "Starts\n W4 Nov" → "W4 Nov"
        start_el = unit_comp.find("span", class_="label-start")
        start = ""
        if start_el:
            inner_span = start_el.find("span")
            if inner_span:
                raw = inner_span.get_text(" ", strip=True)
                start = re.sub(r'^Starts\s*', '', raw).strip()

        # Duration — "4 Weeks" (after stripping the clock SVG)
        duration_el = unit_comp.find("div", class_="unit-duration")
        duration = ""
        if duration_el:
            dur_clone = BeautifulSoup(str(duration_el), "lxml").find("div")
            for svg in dur_clone.find_all("svg"):
                svg.decompose()
            duration = dur_clone.get_text(" ", strip=True)

        # Status: current / completed / upcoming
        comp_classes = unit_comp.get("class", [])
        if "current" in comp_classes:
            status = "current"
        elif "completed" in comp_classes:
            status = "completed"
        else:
            status = "upcoming"

        units.append({
            "id": unit_id,
            "title": title,
            "start": start,
            "duration": duration,
            "status": status,
            "url": f"{BASE_URL}/student/classes/{class_id}/units/{unit_id}/presentations",
        })

    return units


def parse_unit_popup(html: str) -> dict:
    """
    Parse the unit popup fragment (/units/{id}/popup) to extract all IB
    framework fields: global_context, key_concepts, related_concepts,
    conceptual_understanding, statement_of_inquiry, inquiry_questions, atl_skills.
    Also extracts start_date and duration from the <dl> block.
    """
    from bs4 import NavigableString
    soup = BeautifulSoup(html, "lxml")
    result: dict[str, Any] = {}

    # Basic metadata from dt/dd pairs
    for dt in soup.find_all("dt"):
        dd = dt.find_next_sibling("dd")
        label = dt.get_text(" ", strip=True)
        value = dd.get_text(" ", strip=True) if dd else ""
        if "Start date" in label:
            result["start_date"] = value
        elif "Duration" in label:
            result["duration"] = re.sub(r'\s+', ' ', value).strip()

    # IB framework sections
    for section in soup.find_all("div", class_="section"):
        header = section.find("div", class_="unit-component-header")
        if not header:
            continue
        header_text = header.get_text(strip=True)

        if "Global Context" in header_text:
            contexts = []
            for flex in section.find_all("div", class_="flex"):
                clone = BeautifulSoup(str(flex), "lxml").find("div")
                for img in clone.find_all("img"):
                    img.decompose()
                t = clone.get_text(" ", strip=True)
                if t:
                    contexts.append(t)
            result["global_context"] = contexts

        elif "Key Concept" in header_text:
            concepts = []
            for p in section.find_all("p"):
                clone = BeautifulSoup(str(p), "lxml").find("p")
                if not clone:
                    continue
                for img in clone.find_all("img"):
                    img.decompose()
                name_el = clone.find("strong")
                name = name_el.get_text(strip=True) if name_el else ""
                full = clone.get_text(" ", strip=True)
                if name and name in full:
                    definition = full[full.index(name) + len(name):].strip()
                else:
                    definition = full
                    name = full
                if name:
                    concepts.append({"name": name, "definition": definition})
            result["key_concepts"] = concepts

        elif "Related Concept" in header_text:
            for p in section.find_all("p"):
                t = p.get_text(" ", strip=True)
                if t:
                    result["related_concepts"] = [c.strip() for c in t.split(",") if c.strip()]
                    break

        elif "Conceptual Understanding" in header_text:
            body = section.find(class_="fix-body-margins")
            if body:
                result["conceptual_understanding"] = _html_to_markdown(body)

        elif "Statement of Inquiry" in header_text:
            body = section.find(class_="fix-body-margins")
            if body:
                result["statement_of_inquiry"] = _html_to_markdown(body)

        elif "Inquiry Question" in header_text:
            questions = []
            for p in section.find_all("p", class_="mb-1"):
                label_el = p.find("span", class_=re.compile(r"\blabel\b"))
                q_type = label_el.get_text(strip=True) if label_el else ""
                # Get only the direct text nodes (not inside the span)
                q_text = "".join(
                    str(s) for s in p.children
                    if isinstance(s, NavigableString)
                ).strip()
                if q_type or q_text:
                    questions.append({"type": q_type, "question": q_text})
            result["inquiry_questions"] = questions

        elif "ATL" in header_text:
            skills = []
            for flex in section.find_all("div", class_="flex"):
                clone = BeautifulSoup(str(flex), "lxml").find("div")
                for img in clone.find_all("img"):
                    img.decompose()
                t = clone.get_text(" ", strip=True)
                if t:
                    skills.append(t)
            result["atl_skills"] = skills

    return result


async def fetch_units(class_id: str) -> list[dict]:
    cache_key = f"get_units:{class_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    import asyncio as _asyncio

    async with await get_client() as client:
        r = await authed_get(client, f"/student/classes/{class_id}/units")
        units = parse_units(r.text, class_id)

        if not units:
            return []

        # Fetch all unit popups concurrently in the same session
        popup_responses = await _asyncio.gather(*[
            authed_get(client, f"/student/classes/{class_id}/units/{u['id']}/popup")
            for u in units
        ])

    for unit, popup_r in zip(units, popup_responses):
        ib = parse_unit_popup(popup_r.text)
        unit.update(ib)

    cache.set(cache_key, units, "get_units")
    return units


# ---------------------------------------------------------------------------
# File download (raw bytes, no conversion)
# ---------------------------------------------------------------------------

_MAX_FILE_BYTES = 20 * 1024 * 1024   # 20 MB hard limit (Anthropic API PDF cap)
_FILES_CACHE_DIR = None               # set lazily from config


def _file_cache_paths(url: str):
    """Return (meta_path, data_path) for the given URL."""
    import hashlib
    from .config import DATA_DIR
    cache_dir = DATA_DIR / "files"
    cache_dir.mkdir(exist_ok=True)
    h = hashlib.md5(url.encode()).hexdigest()
    return cache_dir / f"{h}.json", cache_dir / f"{h}.bin"


async def fetch_file_bytes(url: str) -> dict[str, Any]:
    """
    Download a ManageBac attachment using the authenticated session and
    return the raw bytes + metadata.  Results are cached to disk for 1 hour.

    Returns:
        {content_type, size_bytes, data (bytes), error (None on success)}
    """
    import json as _json, time as _time

    meta_path, data_path = _file_cache_paths(url)

    # --- disk cache hit ---
    if meta_path.exists() and data_path.exists():
        try:
            meta = _json.loads(meta_path.read_text())
            if _time.time() < meta.get("expires_at", 0):
                return {
                    "content_type": meta["content_type"],
                    "size_bytes": meta["size_bytes"],
                    "data": data_path.read_bytes(),
                    "error": None,
                }
        except Exception:
            pass  # stale / corrupt cache — fall through to re-download

    async with await get_client() as client:
        try:
            r = await authed_get(client, url)
        except Exception as e:
            return {"content_type": "", "size_bytes": 0, "data": b"", "error": f"Download failed: {e}"}

    if r.status_code != 200:
        return {"content_type": "", "size_bytes": 0, "data": b"", "error": f"HTTP {r.status_code}"}

    content_type = r.headers.get("content-type", "application/octet-stream").split(";")[0].strip()
    data = r.content

    if len(data) > _MAX_FILE_BYTES:
        return {
            "content_type": content_type,
            "size_bytes": len(data),
            "data": b"",
            "error": f"File is {len(data) / 1_048_576:.1f} MB — exceeds the 20 MB limit.",
        }

    # --- write disk cache ---
    try:
        meta_path.write_text(_json.dumps({
            "content_type": content_type,
            "size_bytes": len(data),
            "expires_at": int(_time.time()) + 3600,
        }))
        data_path.write_bytes(data)
    except Exception:
        pass  # cache write failure is non-fatal

    return {"content_type": content_type, "size_bytes": len(data), "data": data, "error": None}


# ---------------------------------------------------------------------------
# Task file submission
# ---------------------------------------------------------------------------

async def submit_task_file(
    class_id: str,
    task_id: str,
    file_path: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Upload a local file to a task's dropbox on ManageBac.

    Workflow:
      1. GET the dropbox page to get a fresh CSRF token
      2. POST multipart/form-data to the upload endpoint

    Rails endpoint:
      POST /student/classes/{class_id}/core_tasks/{task_id}/dropbox/upload
      _method=patch
      X-CSRF-Token: <from meta tag>
      dropbox[assets_attributes][0][file]: <file bytes>
      dropbox[assets_attributes][0][file_cache]: ""

    If dry_run=True, validates everything (file exists, task has dropbox)
    but does NOT submit — returns a preview of what would be submitted.
    """
    from pathlib import Path as _Path
    from bs4 import BeautifulSoup as _BS
    import mimetypes as _mimetypes

    path = _Path(file_path)
    if not path.exists():
        return {"success": False, "error": f"File not found: {file_path}"}
    if not path.is_file():
        return {"success": False, "error": f"Not a file: {file_path}"}

    file_size = path.stat().st_size
    if file_size > 500 * 1024 * 1024:
        return {"success": False, "error": f"File too large ({file_size / 1_048_576:.1f} MB). ManageBac limit is 500 MB."}

    mime_type = _mimetypes.guess_type(str(path))[0] or "application/octet-stream"

    async with await get_client() as client:
        # Fetch dropbox page to get CSRF token and confirm dropbox exists
        dropbox_url = f"/student/classes/{class_id}/core_tasks/{task_id}/dropbox"
        r = await authed_get(client, dropbox_url)

        if r.status_code != 200 or "/login" in str(r.url):
            return {"success": False, "error": "Could not access the dropbox page — check class_id and task_id."}

        soup = _BS(r.text, "lxml")
        csrf_el = soup.find("meta", {"name": "csrf-token"})
        if not csrf_el:
            return {"success": False, "error": "Could not find CSRF token on the dropbox page."}
        csrf_token = csrf_el["content"]

        # Confirm the upload form is present
        form = soup.find("form", id=lambda i: i and "dropbox" in i)
        if not form:
            return {"success": False, "error": "No upload form found — this task may not have a submission dropbox."}

        if dry_run:
            return {
                "dry_run": True,
                "would_submit": {
                    "file": str(path),
                    "filename": path.name,
                    "size_bytes": file_size,
                    "mime_type": mime_type,
                    "to_task": f"{BASE_URL}/student/classes/{class_id}/core_tasks/{task_id}",
                    "endpoint": f"{BASE_URL}/student/classes/{class_id}/core_tasks/{task_id}/dropbox/upload",
                },
                "note": "Set dry_run=false to actually submit.",
            }

        # Read file and POST
        file_bytes = path.read_bytes()
        upload_url = f"{BASE_URL}/student/classes/{class_id}/core_tasks/{task_id}/dropbox/upload"

        response = await client.post(
            upload_url,
            data={
                "_method": "patch",
                "dropbox[assets_attributes][0][file_cache]": "",
                "commit": "Upload Files",
            },
            files={
                "dropbox[assets_attributes][0][file]": (path.name, file_bytes, mime_type),
            },
            headers={
                "X-CSRF-Token": csrf_token,
                "X-Requested-With": "XMLHttpRequest",  # Rails UJS sends this
                "Referer": f"{BASE_URL}/student/classes/{class_id}/core_tasks/{task_id}/dropbox",
            },
            follow_redirects=True,
        )

    # Rails data-remote forms respond with JS or JSON on success
    # A 200 with non-login URL means success
    if response.status_code in (200, 201, 204):
        resp_text = response.text[:500] if response.text else ""
        return {
            "success": True,
            "file": path.name,
            "size_bytes": file_size,
            "task_url": f"{BASE_URL}/student/classes/{class_id}/core_tasks/{task_id}",
            "http_status": response.status_code,
            "server_response": resp_text,
        }
    else:
        return {
            "success": False,
            "error": f"Upload failed — HTTP {response.status_code}",
            "server_response": response.text[:300],
        }


# ---------------------------------------------------------------------------
# find_task
# ---------------------------------------------------------------------------

async def find_task(query: str) -> dict | None:
    # URL mode — extract class_id and task_id from a ManageBac URL
    url_match = re.search(r'/classes/(\d+)/core_tasks/(\d+)', query)
    if url_match:
        class_id, task_id = url_match.groups()
        return await fetch_task_detail(class_id, task_id)

    # Title search mode — fuzzy match across all classes
    import difflib
    classes = await fetch_classes()
    best_score = 0.0
    best_task = None
    best_class_id = None

    for cls in classes:
        tasks = await fetch_tasks(cls["id"])
        titles = [t["title"] for t in tasks]
        matches = difflib.get_close_matches(query, titles, n=1, cutoff=0.6)
        if matches:
            score = difflib.SequenceMatcher(None, query.lower(), matches[0].lower()).ratio()
            if score > best_score:
                best_score = score
                matched_task = next(t for t in tasks if t["title"] == matches[0])
                best_task = matched_task
                best_class_id = cls["id"]

    if best_task and best_class_id:
        return await fetch_task_detail(best_class_id, best_task["id"])

    return None
