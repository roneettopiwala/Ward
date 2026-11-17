"""What residents raised about development applications, from planning staff reports.

Every planning decision report has a Community Consultation section in which
staff summarize what residents said at the consultation meeting and in
writing. Those summaries are already de-identified and consistently written,
so each concern becomes one comment, located at its application.

The reports are public PDFs on toronto.ca, but the TMMIS index that lists them
refuses automated access, so the report paths come from a list found by web
search (data/staff_reports.txt). Each PDF is downloaded once, politely, and
only its text is cached. Needs `pdftotext` (poppler-utils).
"""

import logging
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import httpx
from sqlalchemy import Engine, text

from ..config import CACHE_DIR

log = logging.getLogger(__name__)

LIST = Path(__file__).resolve().parent.parent / "data" / "staff_reports.txt"
BASE = "https://www.toronto.ca/legdocs/mmis/"
USER_AGENT = "Ward-research/0.1 (non-commercial city planning simulator)"
PAUSE_S = 1.0
"""Between downloads, to be gentle with the City's server."""
TEXT_CACHE = CACHE_DIR / "staff_reports"

APPLICATION_NUMBER = re.compile(r"\b\d{2} \d{6} [A-Z]{3} \d{2} [A-Z]{2}\b")
REPORT_DATE = re.compile(r"^Date:\s*(\w+ \d{1,2}, \d{4})", re.M)
HEADING = re.compile(
    r"^\s*(community consultation(?: meetings?)?|public consultation|community engagement)\s*$",
    re.I,
)
BULLETS = "•●▪◦\uf0b7\uf0a7\uf076\uf0d8–\\-"
"""Bullet glyphs, including the private-use ones some PDFs draw bullets with."""
BULLET = re.compile(rf"^\s*[{BULLETS}o]\s+")
# Lines that are page furniture, not content.
FURNITURE = re.compile(
    r"Page \d+ of \d+\s*$|^\s*Page\s*$|^\s*\d+\s*$|^~?TORONTO\s*$|"
    r"(?:Decision|Final|Supplementary) Report\s*[-–]|[-–]\s*(?:Approval|Refusal)\s*[-–]"
)
# A section ends at the next heading: an all-caps line, or one of these.
NEXT_HEADINGS = re.compile(
    r"^\s*(statutory public meeting.*|comments|conclusion|contact|signature|attachments?.*|"
    r"agency circulation.*|planning act.*|provincial.*|official plan.*|policy and regulation.*|"
    r"decision history|application description|staff report.*|financial impact|"
    r"equity impact.*|climate.*|reasons for the application|the site|housing.*|"
    r"recommendations?)\s*$",
    re.I,
)
# Staff boilerplate around the residents' points.
BOILERPLATE = re.compile(
    r"(notice of the meeting|were in attendance|attended the meeting|people attended|"
    r"individuals in attendance|presented the|presentation|(?:has|have) been considered|"
    r"were considered|have been addressed|responds? to|was hosted|were hosted|was held|"
    r"is summarized|are summarized|summarized below|following comments|"
    r"comments raised (?:prior|during|include)|include the following|"
    r"included the following|issues raised (?:include|included)|"
    r"concerns? (?:raised )?(?:included|include)[:,]?$|taken into consideration|"
    r"application information centre|advisory body|was posted|were posted|"
    r"participated in|members (?:of the public )?attended|community members attended|"
    r"staff (?:have |has )?(?:also )?received|staff (?:have |has )?reviewed|"
    r"staff (?:have |has )?concluded|in response to|been revised|revisions? to the|"
    r"design review panel|\bDRP\b|members provided|were integrated|be incorporated|"
    r"used to inform|section 37|section 42|\$\d|with regards? to|staff (?:are|is|spoke|met)|"
    r"city staff|the owner|to the satisfaction|demonstrated|satisfactor|satisfied|"
    r"holding provision|staff (?:are |have )?recommend|the applicant (?:has|have) (?:proposed|"
    r"prepared|submitted|revised)|study has|^staff\b|staff worked|meetings? took place|"
    r"been used|the proposed development will|in relation to|^it (?:secures|provides|"
    r"includes|proposes))",
    re.I,
)
EMAIL = re.compile(r"\S+@\S+")
PHONE = re.compile(r"\(?\d{3}\)?[\s.-]?\d{3}[\s.-]\d{4}")
MIN_WORDS = 4
MAX_CHARS = 600


@dataclass
class Report:
    path: str
    title: str
    report_date: date | None
    application_numbers: list[str]
    concerns: list[str] = field(default_factory=list)

    @property
    def url(self) -> str:
        return BASE + self.path + ".pdf"


def report_paths() -> list[str]:
    lines = (line.strip() for line in LIST.read_text().splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def _text(path: str, client: httpx.Client) -> str | None:
    """The report's text, downloaded and extracted once."""
    cached = TEXT_CACHE / (path.replace("/", "_") + ".txt")
    if cached.exists():
        return cached.read_text()
    time.sleep(PAUSE_S)
    r = client.get(BASE + path + ".pdf")
    if r.status_code != 200:
        log.warning("staff report %s: HTTP %d", path, r.status_code)
        return None
    with tempfile.NamedTemporaryFile(suffix=".pdf") as pdf:
        pdf.write(r.content)
        pdf.flush()
        out = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", pdf.name, "-"], capture_output=True, check=True
        ).stdout.decode()
    TEXT_CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(out)
    return out


def _title(lines: list[str]) -> str:
    """The lines between 'REPORT FOR ACTION' and 'Date:'."""
    out: list[str] = []
    started = False
    for line in lines[:30]:
        s = line.strip()
        if s.upper().startswith("REPORT FOR ACTION"):
            started = True
            continue
        if s.startswith("Date:"):
            break
        if started and s and not FURNITURE.search(s):
            out.append(s)
    return " ".join(out)


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 80:
        return False
    if NEXT_HEADINGS.match(s):
        return True
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 4 and all(c.isupper() for c in letters)


def _section(lines: list[str]) -> list[str]:
    """The Community Consultation section's lines, without page furniture."""
    for i, line in enumerate(lines):
        if not HEADING.match(line):
            continue
        body: list[str] = []
        for nxt in lines[i + 1 :]:
            if _is_heading(nxt) and not HEADING.match(nxt):
                break
            if not FURNITURE.search(nxt) and not re.match(r"^(Decision|Final) Report", nxt):
                body.append(nxt)
        if any(line.strip() for line in body):
            return body
    return []


LONE_BULLET = re.compile(rf"^\s*[{BULLETS}]\s*([{BULLETS}]\s*)*$")
LIST_INTRO = re.compile(
    r"(?:include[sd]?(?: the following)?|following|were|are|as follows|related to|"
    r"regarding)\s*:\s*",
    re.I,
)
CONCERN_WORDS = re.compile(
    r"\b(concern|worr|support|oppos|object|question|asked|request|suggest|raised|"
    r"comment|feedback|desire|want|prefer|fear|issue)",
    re.I,
)
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


# Subheadings that name a meeting, a page or an advisory body rather than a topic.
NOT_A_TOPIC = re.compile(
    r"consultation|meeting|^page|^road$|approval|refusal|provision|recommendation|overview|"
    r"issues raised|other comments|working group|panel|;|\band$",
    re.I,
)
# Groups whose views are not residents': their points are skipped.
NOT_RESIDENTS = re.compile(r"panel|working group|agenc|staff", re.I)


def _is_subheading(s: str) -> bool:
    """A short topic line inside the section, e.g. 'Traffic Impact' or 'Parking'."""
    words = s.rstrip(".:").split()
    return (
        0 < len(words) <= 5
        and s[0].isupper()
        and not s.endswith((",", ";"))
        and (not s.endswith(".") or len(words) <= 3)
        and not re.search(r"\b(include|included|includes|raised|following|were|are)\b", s, re.I)
    )


def _ends_item(s: str) -> bool:
    return s.endswith((".", ";", "?")) or s.endswith((" and", " or"))


def _bullet_items(body: list[str]) -> list[str]:
    """Bulleted points, with the topic subheading they sit under, if any.

    pdftotext sometimes puts bullet markers on lines of their own, ahead of the
    lines they belong to; those are matched up in order.
    """
    items: list[str] = []
    current: list[str] = []
    topic = ""
    pending = 0  # lone bullet markers waiting for their text
    in_bullet = False

    def flush() -> None:
        nonlocal in_bullet
        if current and not NOT_RESIDENTS.search(topic):
            label = "" if not topic or NOT_A_TOPIC.search(topic) else f"{topic}: "
            items.append(label + " ".join(current))
        current.clear()
        in_bullet = False

    for line in body:
        s = line.strip()
        if not s:
            continue
        if LONE_BULLET.match(s):
            flush()
            pending += len(re.findall(rf"[{BULLETS}]", s))
            continue
        if BULLET.match(line):
            flush()
            in_bullet = True
            current.append(BULLET.sub("", line).strip())
        elif current and not _ends_item(current[-1]):
            current.append(s)  # the bullet's text continues
        elif _is_subheading(s) and not s.endswith("."):
            flush()
            topic = s.rstrip(":")
            continue
        elif pending:
            flush()
            pending -= 1
            in_bullet = True
            current.append(s)
        else:
            flush()  # prose after the bullets
            continue
        if _ends_item(s) and not pending:
            flush()
        elif _ends_item(s):
            flush()
    flush()
    return items


def _prose_items(body: list[str]) -> list[str]:
    """Lists after 'include the following:', split on semicolons, then concern sentences."""
    text = re.sub(r"\s+", " ", " ".join(line.strip() for line in body)).strip()
    items: list[str] = []
    for sentence in SENTENCE.split(text):
        intro = LIST_INTRO.search(sentence)
        if intro and ";" in sentence[intro.end() :]:
            for part in sentence[intro.end() :].split(";"):
                items.append(re.sub(r"^\s*(and|or)\s+", "", part).strip(" .;"))
        elif CONCERN_WORDS.search(sentence):
            items.append(sentence)
    return items


def _items(body: list[str]) -> list[str]:
    """The residents' points: bullets if the section has them, otherwise from its prose."""
    if any(BULLET.match(line) or LONE_BULLET.match(line.strip() or "x") for line in body):
        items = _bullet_items(body)
        if items:
            return items
    return _prose_items(body)


def _clean(item: str) -> str | None:
    item = re.sub(r"\s+", " ", item).strip()
    item = re.sub(r"[;,]?\s*(and|or)?\s*$", "", item).strip().rstrip(";").strip()
    item = PHONE.sub("[phone]", EMAIL.sub("[email]", item))
    if len(item.split()) < MIN_WORDS or len(item) > MAX_CHARS or BOILERPLATE.search(item):
        return None
    item = item[0].upper() + item[1:]
    return item if item.endswith((".", "?", "!")) else item + "."


MENTION = re.compile(
    r"(at the (?:community )?consultation meeting|residents|community members|members of the "
    r"public|the community|attendees)[^.]*\b(concern|interest|support|oppos|raised|expressed|"
    r"question|asked|request)",
    re.I,
)


def _mentions(raw: str) -> list[str]:
    """When there is no section: sentences elsewhere that report what residents said."""
    text = re.sub(r"\s+", " ", raw)
    return [s for s in SENTENCE.split(text) if MENTION.search(s) and len(s) < MAX_CHARS]


def parse(path: str, raw: str) -> Report:
    lines = raw.splitlines()
    head = "\n".join(lines[:60])
    when = REPORT_DATE.search(head)
    numbers = list(dict.fromkeys(APPLICATION_NUMBER.findall(head)))
    report = Report(
        path=path,
        title=_title(lines),
        report_date=datetime.strptime(when.group(1), "%B %d, %Y").date() if when else None,
        application_numbers=numbers or list(dict.fromkeys(APPLICATION_NUMBER.findall(raw)))[:1],
    )
    seen: set[str] = set()
    items = _items(_section(lines)) or _mentions(raw)
    for item in items:
        cleaned = _clean(item)
        if cleaned and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            report.concerns.append(cleaned)
    return report


def load() -> list[Report]:
    reports: list[Report] = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120) as client:
        for path in report_paths():
            raw = _text(path, client)
            if raw:
                reports.append(parse(path, raw))
    with_concerns = [r for r in reports if r.concerns]
    log.info(
        "staff reports: %d read, %d with consultation comments, %d comments",
        len(reports),
        len(with_concerns),
        sum(len(r.concerns) for r in with_concerns),
    )
    return with_concerns


def ingest(eng: Engine) -> int:
    rows = []
    seen: set[tuple[str | None, str]] = set()
    # Newest report first, so an application's later report keeps a repeated point.
    for r in sorted(load(), key=lambda r: r.report_date or date.min, reverse=True):
        app = r.application_numbers[0] if r.application_numbers else None
        for i, concern in enumerate(r.concerns):
            if (app, concern.lower()) in seen:
                continue
            seen.add((app, concern.lower()))
            rows.append(
                {
                    "id": f"staff:{r.path.replace('/bgrd/backgroundfile-', '/')}:{i}",
                    "url": r.url,
                    "app": app,
                    "apps": r.application_numbers,
                    "title": r.title,
                    "date": r.report_date,
                    "text": concern,
                }
            )
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM comments WHERE source = 'staff_report'"))
        for row in rows:
            # Located at the first of the report's applications that the open data has.
            conn.execute(
                text(
                    """
                    INSERT INTO comments (id, source, source_url, application_number,
                                          report_title, report_date, text,
                                          neighbourhood_id, geom)
                    SELECT :id, 'staff_report', :url, COALESCE(a.application_number, :app),
                           :title, :date, :text, a.neighbourhood_id, a.geom
                    FROM (SELECT 1) one
                    LEFT JOIN LATERAL (
                        SELECT * FROM applications
                        WHERE application_number = ANY(:apps)
                        ORDER BY array_position(:apps, application_number)
                        LIMIT 1
                    ) a ON true
                    """
                ),
                row,
            )
        located = conn.scalar(
            text("SELECT count(*) FROM comments WHERE source = 'staff_report' AND geom IS NOT NULL")
        )
    log.info("staff report comments: %d, %d located", len(rows), located)
    return len(rows)
