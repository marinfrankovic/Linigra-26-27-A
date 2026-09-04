"""Gradi ICS, CSV i GitHub Pages stranicu s rasporedom razreda 1.A (LINIGRA).

Izvori:
  * EduPage aSc timetable API (linigra.edupage.org) - raspored po tjednu
  * javni Google kalendar "Skolski praznici HR" - pocetak/kraj polugodista i praznici

Pokretanje:  python scripts/build.py
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Konfiguracija
# --------------------------------------------------------------------------- #

EDUPAGE_HOST = "https://linigra.edupage.org"
TTVIEWER_URL = f"{EDUPAGE_HOST}/timetable/server/ttviewer.js?__func=getTTViewerData"
REGULARTT_URL = f"{EDUPAGE_HOST}/timetable/server/regulartt.js?__func=regularttGetData"

HOLIDAYS_ICS = (
    "https://calendar.google.com/calendar/ical/"
    "99acf140bfd2f5a0f6d41ba75f888cc95dc47bfdd221eb84f594b8d7f840074e"
    "%40group.calendar.google.com/public/basic.ics"
)

CLASS_NAME = os.environ.get("LINIGRA_CLASS", "1.A")
SCHOOL_YEAR_START = int(os.environ.get("LINIGRA_YEAR", "2026"))
SCHOOL_NAME = "LINIGRA – privatna škola s pravom javnosti"
SCHOOL_ADDRESS = "Gjure Szaba 4, 10000 Zagreb"
TIMEZONE_ID = "Europe/Zagreb"

SITE_BASE = os.environ.get(
    "SITE_BASE_URL", "https://marinfrankovic.github.io/Linigra-26-27-A"
).rstrip("/")

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
DATA = DOCS / "data"

ICS_NAME = "linigra-1a.ics"
CSV_NAME = "linigra-1a.csv"

# Rezerva ako se kalendar praznika ne uspije preuzeti.
FALLBACK_TERM_START = date(SCHOOL_YEAR_START, 9, 7)
FALLBACK_TERM_END = date(SCHOOL_YEAR_START, 12, 23)

# Susjedne satove istog predmeta spajamo u jedan upis samo ako je pauza kratka,
# da se ne proglasi velika pauza (12:05-12:35) nastavom.
MERGE_GAP_MIN = 10

DAY_NAMES_HR = ["Ponedjeljak", "Utorak", "Srijeda", "Četvrtak", "Petak"]

# Cjelodnevni upisi iz kalendara praznika koji ne znace prekid nastave.
INFO_ONLY = ("prvi dan škole", "zadnji dan nastave")


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


# GitHub runneri nemaju IPv6 izlaz, a EduPage i Google objavljuju AAAA zapise.
_getaddrinfo = socket.getaddrinfo


def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _ipv4_only


def _retry(fn, attempts: int = 4):
    for i in range(attempts):
        try:
            return fn()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            if i == attempts - 1:
                raise
            wait = 2 ** i
            print(f"mrežna greška ({exc}); ponovni pokušaj za {wait}s")
            time.sleep(wait)


def http_json(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "linigra-raspored/1.0"},
    )

    def call() -> dict:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    return _retry(call)


def http_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "linigra-raspored/1.0"})

    def call() -> str:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode("utf-8")

    return _retry(call)


# --------------------------------------------------------------------------- #
# Kalendar praznika (ICS)
# --------------------------------------------------------------------------- #


@dataclass
class Holiday:
    summary: str
    start: date
    end: date  # ukljucivo

    @property
    def days(self) -> list[date]:
        out, d = [], self.start
        while d <= self.end:
            out.append(d)
            d += timedelta(days=1)
        return out


def unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def parse_holidays(text: str) -> list[Holiday]:
    out: list[Holiday] = []
    cur: dict[str, str] = {}
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if {"SUMMARY", "DTSTART"} <= cur.keys():
                start = datetime.strptime(cur["DTSTART"][:8], "%Y%m%d").date()
                end = (
                    datetime.strptime(cur["DTEND"][:8], "%Y%m%d").date() - timedelta(days=1)
                    if cur.get("DTEND")
                    else start
                )
                out.append(Holiday(cur["SUMMARY"].strip(), start, max(start, end)))
            cur = {}
        elif ":" in line:
            name, value = line.split(":", 1)
            key = name.split(";", 1)[0].upper()
            if key in ("SUMMARY", "DTSTART", "DTEND"):
                cur[key] = value.replace("\\,", ",").replace("\\;", ";")
    return out


def term_bounds(holidays: list[Holiday]) -> tuple[date, date]:
    """Prvi nastavni dan i zadnji dan 1. polugodista iz kalendara praznika."""
    start = end = None
    for h in holidays:
        low = h.summary.lower()
        if "prvi dan škole" in low and h.start.year == SCHOOL_YEAR_START:
            start = h.start
        if "zimski odmor" in low and "1. dio" in low and h.start.year == SCHOOL_YEAR_START:
            end = h.start - timedelta(days=1)
    return start or FALLBACK_TERM_START, end or FALLBACK_TERM_END


def easter(year: int) -> date:
    """Uskrsna nedjelja po gregorijanskom (anonimnom) algoritmu."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def statutory_holidays(year: int) -> dict[date, str]:
    """Svih 14 neradnih dana po Zakonu o blagdanima (NN 110/2019)."""
    us = easter(year)
    return {
        date(year, 1, 1): "Nova godina",
        date(year, 1, 6): "Sveta tri kralja",
        us: "Uskrs",
        us + timedelta(days=1): "Uskrsni ponedjeljak",
        date(year, 5, 1): "Praznik rada",
        date(year, 5, 30): "Dan državnosti",
        us + timedelta(days=60): "Tijelovo",
        date(year, 6, 22): "Dan antifašističke borbe",
        date(year, 8, 5): "Dan pobjede i domovinske zahvalnosti",
        date(year, 8, 15): "Velika Gospa",
        date(year, 11, 1): "Svi sveti",
        date(year, 11, 18): "Dan sjećanja na žrtve Domovinskog rata",
        date(year, 12, 25): "Božić",
        date(year, 12, 26): "Sveti Stjepan",
    }


def no_school_days(holidays: list[Holiday], start: date, end: date) -> dict[date, str]:
    out: dict[date, str] = {}
    for h in holidays:
        if any(tag in h.summary.lower() for tag in INFO_ONLY):
            continue
        for d in h.days:
            if start <= d <= end and d.weekday() <= 4:
                out[d] = h.summary
    return out


# --------------------------------------------------------------------------- #
# EduPage raspored
# --------------------------------------------------------------------------- #


@dataclass
class Lesson:
    subject: str
    short: str
    teachers: list[str]
    groups: list[str]
    rooms: list[str]


@dataclass
class Block:
    weekday: int
    start: str
    end: str
    periods: list[int]
    lesson: Lesson


@dataclass
class Variant:
    """Jedna verzija rasporeda i razdoblje u kojem vrijedi."""

    tt_num: str
    label: str
    valid_from: date
    valid_to: date
    blocks: list[Block] = field(default_factory=list)
    periods: dict[str, dict] = field(default_factory=dict)


def fetch_variants() -> list[dict]:
    data = http_json(TTVIEWER_URL, {"__args": [None, SCHOOL_YEAR_START], "__gsh": "00000000"})
    regular = data["r"]["regular"]
    items = [
        t
        for t in regular["timetables"]
        if not t.get("hidden") and int(t.get("year", 0)) == SCHOOL_YEAR_START
    ]
    if not items:
        items = [t for t in regular["timetables"] if t["tt_num"] == regular.get("default_num")]
    return sorted(items, key=lambda t: t["datefrom"])


def fetch_tables(tt_num: str) -> dict[str, list[dict]]:
    data = http_json(REGULARTT_URL, {"__args": [None, str(tt_num)], "__gsh": "00000000"})
    return {t["id"]: t["data_rows"] for t in data["r"]["dbiAccessorRes"]["tables"]}


def weekly_blocks(tables: dict[str, list[dict]]) -> tuple[dict[str, dict], list[Block]]:
    idx = lambda name: {r["id"]: r for r in tables[name]}
    periods, subjects = idx("periods"), idx("subjects")
    teachers, classrooms = idx("teachers"), idx("classrooms")
    groups, lessons, classes = idx("groups"), idx("lessons"), idx("classes")

    class_id = next((c["id"] for c in classes.values() if c["name"] == CLASS_NAME), None)
    if class_id is None:
        raise SystemExit(f"Razred {CLASS_NAME} nije pronađen u rasporedu.")

    slots: dict[tuple[int, int], Lesson] = {}
    for card in tables["cards"]:
        les = lessons[card["lessonid"]]
        if class_id not in (les.get("classids") or []):
            continue
        lesson = Lesson(
            subject=subjects[les["subjectid"]]["name"],
            short=subjects[les["subjectid"]]["short"],
            teachers=[teachers[t]["name"] for t in les.get("teacherids") or [] if t in teachers],
            groups=[
                groups[g]["name"]
                for g in les.get("groupids") or []
                if g in groups and groups[g]["classid"] == class_id
                and not groups[g].get("entireclass")
            ],
            rooms=[classrooms[r]["short"] for r in card.get("classroomids") or [] if r in classrooms],
        )
        base = int(card["period"])
        for k in range(int(les.get("durationperiods") or 1)):
            for wd, flag in enumerate(card["days"]):
                if flag == "1":
                    slots[(wd, base + k)] = lesson

    order = sorted((int(p) for p in periods), key=int)
    blocks: list[Block] = []
    for wd in range(5):
        run: Block | None = None
        for p in order:
            cur = slots.get((wd, p))
            meta = periods[str(p)]
            if cur is None:
                if run is not None:
                    blocks.append(run)
                    run = None
                continue
            same = (
                run is not None
                and (run.lesson.subject, tuple(run.lesson.teachers), tuple(run.lesson.rooms))
                == (cur.subject, tuple(cur.teachers), tuple(cur.rooms))
            )
            if same:
                gap = (
                    datetime.strptime(meta["starttime"], "%H:%M")
                    - datetime.strptime(run.end, "%H:%M")
                ).seconds // 60
                if gap <= MERGE_GAP_MIN:
                    run.end = meta["endtime"]
                    run.periods.append(p)
                    continue
            if run:
                blocks.append(run)
            run = Block(wd, meta["starttime"], meta["endtime"], [p], cur)
        if run:
            blocks.append(run)
    return periods, sorted(blocks, key=lambda b: (b.weekday, b.start))


def build_variants(term_start: date, term_end: date) -> list[Variant]:
    listing = fetch_variants()
    variants: list[Variant] = []
    for i, item in enumerate(listing):
        frm = datetime.strptime(item["datefrom"], "%Y-%m-%d").date()
        nxt = (
            datetime.strptime(listing[i + 1]["datefrom"], "%Y-%m-%d").date() - timedelta(days=1)
            if i + 1 < len(listing)
            else term_end
        )
        lo, hi = max(frm, term_start), min(nxt, term_end)
        if lo > hi:
            continue
        # Zadnji objavljeni raspored vrijedi do kraja polugodista.
        if i + 1 == len(listing):
            hi = term_end
        periods, blocks = weekly_blocks(fetch_tables(item["tt_num"]))
        variants.append(
            Variant(str(item["tt_num"]), item.get("text", ""), lo, hi, blocks, periods)
        )
    if not variants:
        raise SystemExit("EduPage nije vratio ni jedan raspored za ovu školsku godinu.")
    return variants


# --------------------------------------------------------------------------- #
# Dogadaji
# --------------------------------------------------------------------------- #


@dataclass
class Event:
    uid: str
    summary: str
    start: date
    end: date
    start_time: str | None
    end_time: str | None
    location: str
    description: str
    all_day: bool


def title(lesson: Lesson) -> str:
    text = f"{lesson.subject} ({lesson.short})"
    if lesson.groups:
        text += " – " + ", ".join(lesson.groups)
    return text


def make_uid(*parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:20]
    return f"{digest}@linigra-{CLASS_NAME.lower().replace('.', '')}"


def expand(
    variants: list[Variant], term_start: date, term_end: date, closed: dict[date, str]
) -> list[Event]:
    events: list[Event] = []
    for variant in variants:
        per_day: dict[int, list[Block]] = {}
        for b in variant.blocks:
            per_day.setdefault(b.weekday, []).append(b)
        day = max(variant.valid_from, term_start)
        while day <= min(variant.valid_to, term_end):
            if day.weekday() <= 4 and day not in closed:
                for b in per_day.get(day.weekday(), []):
                    les = b.lesson
                    room = ", ".join(les.rooms) or CLASS_NAME
                    events.append(
                        Event(
                            uid=make_uid(day.isoformat(), str(b.periods[0]), les.short),
                            summary=title(les),
                            start=day,
                            end=day,
                            start_time=b.start,
                            end_time=b.end,
                            location=f"{room} – {SCHOOL_NAME}, {SCHOOL_ADDRESS}",
                            description=(
                                f"Razred {CLASS_NAME}\\n"
                                f"Predmet: {les.subject} ({les.short})\\n"
                                f"Nastavnik: {', '.join(les.teachers) or '–'}\\n"
                                f"Učionica: {room}\\n"
                                f"Sat: {', '.join(map(str, b.periods))}"
                            ),
                            all_day=False,
                        )
                    )
            day += timedelta(days=1)
    return events


def holiday_events(
    holidays: list[Holiday],
    statutory: dict[date, str],
    term_start: date,
    term_end: date,
) -> list[Event]:
    out: list[Event] = []
    covered: set[date] = set()
    window_end = term_end + timedelta(days=21)
    for h in holidays:
        if not (term_start <= h.start <= window_end):
            continue
        covered.update(h.days)
        info = any(tag in h.summary.lower() for tag in INFO_ONLY)
        summary = h.summary if info else f"{h.summary} – nema nastave"
        out.append(
            Event(
                uid=make_uid("praznik", h.start.isoformat(), h.summary),
                summary=summary,
                start=h.start,
                end=h.end,
                start_time=None,
                end_time=None,
                location=f"{SCHOOL_NAME}, {SCHOOL_ADDRESS}",
                description="Izvor: javni kalendar Školski praznici HR",
                all_day=True,
            )
        )
    for day, name in sorted(statutory.items()):
        if not (term_start <= day <= window_end) or day in covered:
            continue
        out.append(
            Event(
                uid=make_uid("blagdan", day.isoformat(), name),
                summary=f"{name} – nema nastave" if day.weekday() <= 4 else name,
                start=day,
                end=day,
                start_time=None,
                end_time=None,
                location=f"{SCHOOL_NAME}, {SCHOOL_ADDRESS}",
                description="Državni blagdan, Zakon o blagdanima (NN 110/2019)",
                all_day=True,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Zapis ICS / CSV
# --------------------------------------------------------------------------- #

VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Europe/Zagreb
X-LIC-LOCATION:Europe/Zagreb
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE"""


def esc(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    raw = line.encode("utf-8")
    if len(raw) <= 73:
        return line
    parts, cur = [], b""
    for ch in line:
        enc = ch.encode("utf-8")
        limit = 73 if not parts else 72
        if len(cur) + len(enc) > limit:
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += enc
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


def render_ics(events: list[Event], stamp: str, sequence: int, cal_name: str) -> str:
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Linigra raspored//1.A 2026-2027//HR",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{esc(cal_name)}",
        f"X-WR-CALDESC:{esc('Raspored razreda ' + CLASS_NAME + ' - ' + SCHOOL_NAME)}",
        f"X-WR-TIMEZONE:{TIMEZONE_ID}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
        *VTIMEZONE.split("\n"),
    ]
    for ev in sorted(events, key=lambda e: (e.start, e.start_time or "")):
        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{ev.uid}")
        lines.append(f"DTSTAMP:{stamp}")
        lines.append(f"LAST-MODIFIED:{stamp}")
        lines.append(f"SEQUENCE:{sequence}")
        if ev.all_day:
            lines.append(f"DTSTART;VALUE=DATE:{ev.start:%Y%m%d}")
            lines.append(f"DTEND;VALUE=DATE:{ev.end + timedelta(days=1):%Y%m%d}")
            lines.append("TRANSP:TRANSPARENT")
        else:
            lines.append(
                f"DTSTART;TZID={TIMEZONE_ID}:{ev.start:%Y%m%d}T{ev.start_time.replace(':', '')}00"
            )
            lines.append(
                f"DTEND;TZID={TIMEZONE_ID}:{ev.end:%Y%m%d}T{ev.end_time.replace(':', '')}00"
            )
            lines.append("TRANSP:OPAQUE")
        lines.append(f"SUMMARY:{esc(ev.summary)}")
        lines.append(f"LOCATION:{esc(ev.location)}")
        lines.append(f"DESCRIPTION:{esc(ev.description)}")
        lines.append("STATUS:CONFIRMED")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(fold(x) for x in lines) + "\r\n"


CSV_FIELDS = [
    "Subject",
    "Start Date",
    "Start Time",
    "End Date",
    "End Time",
    "All day event",
    "Location",
    "Description",
    "Reminder On/Off",
]


def write_csv(events: list[Event], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for ev in sorted(events, key=lambda e: (e.start, e.start_time or "")):
            writer.writerow(
                {
                    "Subject": ev.summary,
                    "Start Date": ev.start.isoformat(),
                    "Start Time": ev.start_time or "",
                    "End Date": ev.end.isoformat(),
                    "End Time": ev.end_time or "",
                    "All day event": "True" if ev.all_day else "False",
                    "Location": ev.location,
                    "Description": ev.description.replace("\\n", " | "),
                    "Reminder On/Off": "Off",
                }
            )


# --------------------------------------------------------------------------- #
# Stranica
# --------------------------------------------------------------------------- #


def weekly_table_html(variant: Variant) -> str:
    per_day: dict[int, list[Block]] = {}
    for b in variant.blocks:
        per_day.setdefault(b.weekday, []).append(b)
    cols = []
    for wd in range(5):
        rows = []
        for b in per_day.get(wd, []):
            les = b.lesson
            room = ", ".join(les.rooms) or CLASS_NAME
            rows.append(
                "<li><span class='t'>{start}–{end}</span>"
                "<span class='s'>{subject}</span>"
                "<span class='m'>{short} · {teacher} · {room}</span></li>".format(
                    start=b.start,
                    end=b.end,
                    subject=html.escape(les.subject),
                    short=html.escape(les.short),
                    teacher=html.escape(", ".join(les.teachers) or "–"),
                    room=html.escape(room),
                )
            )
        cols.append(
            f"<div class='day'><h3>{DAY_NAMES_HR[wd]}</h3><ul>{''.join(rows) or '<li>—</li>'}</ul></div>"
        )
    return "<div class='week'>" + "".join(cols) + "</div>"


ICON_GOOGLE = (
    "<svg viewBox='0 0 24 24' aria-hidden='true'>"
    "<rect x='2.5' y='3.5' width='19' height='17' rx='3' fill='#fff' stroke='#4285f4'"
    " stroke-width='1.6'/><path d='M2.5 8h19' stroke='#4285f4' stroke-width='1.6'/>"
    "<rect x='6' y='11' width='4' height='4' rx='.8' fill='#4285f4'/>"
    "<path d='M7.5 2v3M16.5 2v3' stroke='#4285f4' stroke-width='1.6'"
    " stroke-linecap='round'/></svg>"
)
ICON_APPLE = (
    "<svg viewBox='0 0 24 24' aria-hidden='true'>"
    "<path fill='#e8453c' d='M12 6.4c2.6-2.3 6.6-1.5 8 1.4 1.4 2.9.2 7-3.2 9.9-1.8 1.5-3.1 2.4"
    "-4.8 2.4s-3-.9-4.8-2.4C3.8 14.8 2.6 10.7 4 7.8c1.4-2.9 5.4-3.7 8-1.4z'/>"
    "<path fill='#3f9142' d='M12.4 6.1c-.2-1.6.8-3.2 2.3-3.9.3 1.7-.7 3.4-2.3 3.9z'/></svg>"
)
ICON_OUTLOOK = (
    "<svg viewBox='0 0 24 24' aria-hidden='true'>"
    "<rect x='2.5' y='5' width='10' height='14' rx='2' fill='#0f6cbd'/>"
    "<ellipse cx='7.5' cy='12' rx='2.4' ry='3' fill='#fff'/>"
    "<path d='M13.5 7.5h8v9h-8z' fill='#a3c7ea'/>"
    "<path d='M13.5 8.2l4 2.8 4-2.8' fill='none' stroke='#0f6cbd' stroke-width='1.3'/></svg>"
)
ICON_M365 = (
    "<svg viewBox='0 0 24 24' aria-hidden='true'>"
    "<path fill='#e8563f' d='M3 6.5 13 3v18L3 17.5z'/>"
    "<path fill='#f2a33c' d='M13 3l8 3v12l-8 3z' opacity='.85'/></svg>"
)
ICON_LINK = (
    "<svg viewBox='0 0 24 24' aria-hidden='true' fill='none' stroke='#6b5b4c'"
    " stroke-width='1.7' stroke-linecap='round'>"
    "<path d='M9.5 14.5l5-5'/><path d='M12.5 7.5l1.8-1.8a3.5 3.5 0 015 5L17.5 12.5'/>"
    "<path d='M11.5 16.5l-1.8 1.8a3.5 3.5 0 01-5-5L6.5 11.5'/></svg>"
)


def render_html(ctx: dict) -> str:
    ics_url = f"{SITE_BASE}/{ICS_NAME}"
    webcal = ics_url.replace("https://", "webcal://")
    quoted_ics = urllib.parse.quote(ics_url, safe="")
    cal_title = urllib.parse.quote(f"LINIGRA {CLASS_NAME} raspored", safe="")
    google = "https://calendar.google.com/calendar/r?cid=" + urllib.parse.quote(webcal, safe="")
    outlook_com = (
        f"https://outlook.live.com/calendar/0/addfromweb?url={quoted_ics}&name={cal_title}"
    )
    outlook_365 = (
        f"https://outlook.office.com/calendar/0/addfromweb?url={quoted_ics}&name={cal_title}"
    )

    closed_rows = "".join(
        f"<li><strong>{d.strftime('%d. %m. %Y.')}</strong> · {DAY_NAMES_HR[d.weekday()].lower()}"
        f" – {html.escape(name)}</li>"
        for d, name in sorted(ctx["closed"].items())
    ) or "<li>Nema neradnih dana unutar polugodišta.</li>"

    milestone_rows = "".join(
        f"<li><strong>{label}</strong> – {html.escape(name)}</li>"
        for label, name in ctx["milestones"]
    )

    variant_rows = "".join(
        "<li><strong>{frm} – {to}</strong> · EduPage raspored #{num}{label}</li>".format(
            frm=v.valid_from.strftime("%d. %m. %Y."),
            to=v.valid_to.strftime("%d. %m. %Y."),
            num=html.escape(v.tt_num),
            label=f" · {html.escape(v.label)}" if v.label else "",
        )
        for v in ctx["variants"]
    )

    bells = "".join(
        f"<li><span class='n'>{p['period']}.</span> {p['starttime']}–{p['endtime']}</li>"
        for p in sorted(ctx["variants"][-1].periods.values(), key=lambda x: int(x["period"]))
    )

    return f"""<!DOCTYPE html>
<html lang="hr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Raspored {CLASS_NAME} · LINIGRA {SCHOOL_YEAR_START}./{SCHOOL_YEAR_START + 1}.</title>
<meta name="description" content="Raspored razreda {CLASS_NAME} u školi LINIGRA za školsku godinu {SCHOOL_YEAR_START}./{SCHOOL_YEAR_START + 1}. Pretplati se jednom i promjene dolaze same.">
<meta property="og:title" content="Raspored {CLASS_NAME} · LINIGRA {SCHOOL_YEAR_START}./{SCHOOL_YEAR_START + 1}.">
<meta property="og:description" content="Pretplati se jednom, promjene dolaze same u tvoj kalendar.">
<meta property="og:type" content="website">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'%3E%3Ctext y='.9em' font-size='90'%3E%F0%9F%93%85%3C/text%3E%3C/svg%3E">
<link rel="stylesheet" href="style.css">
</head>
<body>
<header class="hero">
  <p class="kicker">Pretplati se jednom</p>
  <h1>Raspored {CLASS_NAME}<span>LINIGRA · {SCHOOL_YEAR_START}./{SCHOOL_YEAR_START + 1}.</span></h1>
  <p class="lede">Kalendar nije za uvoz nego za pretplatu. Škola objavi novi raspored,
  ovaj se kalendar sam osvježi u ponedjeljak i srijedu, a promjena stigne u tvoju
  aplikaciju bez da išta radiš.</p>
  <div class="cta">
    <div class="addcal">
      <button class="btn primary" type="button" id="addBtn" aria-expanded="false" aria-controls="addMenu">
        <span class="btn-ico">{ICON_GOOGLE}</span> Dodaj u svoj kalendar
      </button>
      <div class="popover" id="addMenu" role="menu" hidden>
        <p class="pop-title">Dodaj u svoj kalendar</p>
        <p class="pop-sub">LINIGRA {CLASS_NAME} · raspored {SCHOOL_YEAR_START}./{SCHOOL_YEAR_START + 1}.</p>
        <a class="opt" role="menuitem" href="{google}" target="_blank" rel="noopener">
          <span class="ico">{ICON_GOOGLE}</span><span class="lbl">Google Kalendar</span><span class="hint">na webu</span></a>
        <a class="opt" role="menuitem" href="{webcal}">
          <span class="ico">{ICON_APPLE}</span><span class="lbl">Apple Kalendar</span><span class="hint">iPhone, iPad, Mac</span></a>
        <a class="opt" role="menuitem" href="{outlook_com}" target="_blank" rel="noopener">
          <span class="ico">{ICON_OUTLOOK}</span><span class="lbl">Outlook.com</span><span class="hint">osobni račun</span></a>
        <a class="opt" role="menuitem" href="{outlook_365}" target="_blank" rel="noopener">
          <span class="ico">{ICON_M365}</span><span class="lbl">Microsoft 365</span><span class="hint">škola ili posao</span></a>
        <button class="opt" role="menuitem" type="button" data-copy="{ics_url}">
          <span class="ico">{ICON_LINK}</span><span class="lbl">Kopiraj adresu</span><span class="hint">.ics adresa</span></button>
        <a class="steps" href="#upute">Upute korak po korak</a>
      </div>
    </div>
    <a class="btn ghost" href="{CSV_NAME}" download>Preuzmi CSV za uvoz</a>
  </div>
  <p class="url"><code id="icsurl">{ics_url}</code></p>
</header>

<main>
<section class="cards">
  <article class="card">
    <h2>Što je unutra</h2>
    <p>Svi nastavni sati razreda {CLASS_NAME} za 1. polugodište, s predmetom,
    nastavnikom, učionicom i rednim brojem sata. Praznici i neradni dani upisani su
    kao cjelodnevni događaji i tada nastave nema.</p>
    <ul class="facts">
      <li><strong>{ctx['lesson_count']}</strong> nastavnih upisa</li>
      <li><strong>{ctx['school_days']}</strong> nastavnih dana</li>
      <li><strong>{ctx['term_start'].strftime('%d. %m. %Y.')} – {ctx['term_end'].strftime('%d. %m. %Y.')}</strong></li>
      <li>bez podsjetnika (reminders)</li>
    </ul>
  </article>
  <article class="card">
    <h2>Kako radi</h2>
    <p>Kalendar živi na ovoj adresi kao <code>.ics</code>. Google, Apple i Outlook je
    povremeno ponovno pročitaju, pa dobiju ono što je zadnje objavljeno. Nema
    aplikacije za instalirati i nema računa za otvoriti.</p>
    <p>Ako ti treba jednokratni uvoz u Outlook, tu je i
    <a href="{CSV_NAME}" download>CSV datoteka</a> te
    <a href="{ICS_NAME}" download>.ics za skidanje</a>.</p>
  </article>
</section>

<section>
  <h2>Tjedni raspored</h2>
  <p class="note">Prikaz vrijedi za raspored koji je trenutno objavljen na EduPageu.
  Stranica se gradi iz istog izvora iz kojeg se gradi i kalendar, pa je ovo točno ono
  što stiže u tvoju aplikaciju.</p>
  {ctx['week_html']}
</section>

<section class="split">
  <div>
    <h2>Raspored zvona</h2>
    <ul class="bells">{bells}</ul>
  </div>
  <div>
    <h2>Važni datumi</h2>
    <ul class="plain">{milestone_rows}</ul>
    <h2>Blagdani koji padaju na nastavni dan</h2>
    <ul class="plain">{closed_rows}</ul>
    <p class="note small">Popis je kratak jer u ovom polugodištu samo jedan državni blagdan
    pada na radni dan. Svi sveti (1. 11.) padaju u nedjelju, a Božić i Sveti Stjepan su
    već unutar zimskog odmora. Kalendar sam izbacuje nastavu na svih 14 neradnih dana iz
    Zakona o blagdanima, uključujući pomične datume oko Uskrsa. Dane koje škola sama
    proglasi nenastavnima (Dan škole, stručno usavršavanje) ovdje nema jer nisu objavljeni
    ni u jednom javnom kalendaru.</p>
    <h2>Verzije rasporeda</h2>
    <ul class="plain">{variant_rows}</ul>
  </div>
</section>

<section id="upute">
  <h2>Upute po aplikaciji</h2>
  <div class="howto">
    <details open>
      <summary>Google Kalendar</summary>
      <p>Klikni <em>Dodaj u Google Kalendar</em> gore. Ili ručno: Google Kalendar →
      <em>Ostali kalendari</em> → <em>+</em> → <em>Pretplati se putem URL-a</em> →
      zalijepi <code>{ics_url}</code>.</p>
    </details>
    <details>
      <summary>iPhone / iPad / Mac</summary>
      <p>Klikni <em>Dodaj u Apple Kalendar</em> i potvrdi. Ručno na iPhoneu:
      <em>Postavke</em> → <em>Aplikacije</em> → <em>Kalendar</em> → <em>Računi</em> →
      <em>Dodaj račun</em> → <em>Ostalo</em> → <em>Dodaj kalendar pretplate</em> →
      zalijepi adresu.</p>
    </details>
    <details>
      <summary>Outlook (web i novi Outlook)</summary>
      <p><em>Kalendar</em> → <em>Dodaj kalendar</em> → <em>Pretplati se s weba</em> →
      zalijepi <code>{ics_url}</code> → daj mu ime i spremi.</p>
    </details>
    <details>
      <summary>Outlook (klasični, samo uvoz)</summary>
      <p>Pretplata se osvježava sama, uvoz ne. Ako ipak želiš uvoz:
      <em>File</em> → <em>Open &amp; Export</em> → <em>Import/Export</em> →
      <em>Import from another program or file</em> → <em>Comma Separated Values</em> →
      odaberi <a href="{CSV_NAME}" download>{CSV_NAME}</a>.</p>
    </details>
  </div>
</section>
</main>

<footer>
  <p>Izvor rasporeda: <a href="https://linigra.edupage.org/timetable/" target="_blank" rel="noopener">EduPage stranica škole LINIGRA</a>.
  Izvor praznika: javni kalendar <em>Školski praznici HR</em>.</p>
  <p>Zadnja provjera: <strong>{ctx['checked_at']}</strong> · zadnja promjena kalendara:
  <strong>{ctx['changed_at']}</strong> · provjera ponedjeljkom i srijedom.</p>
  <p class="fine">Neslužbeni kalendar. Kod raspored škole i objave na EduPageu ima prednost.</p>
</footer>

<script>
(function () {{
  var btn = document.getElementById('addBtn');
  var menu = document.getElementById('addMenu');
  function close() {{ menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); }}
  btn.addEventListener('click', function (e) {{
    e.stopPropagation();
    menu.hidden = !menu.hidden;
    btn.setAttribute('aria-expanded', String(!menu.hidden));
  }});
  document.addEventListener('click', function (e) {{
    if (!menu.hidden && !menu.contains(e.target)) close();
  }});
  document.addEventListener('keydown', function (e) {{ if (e.key === 'Escape') close(); }});
  menu.querySelectorAll('a[href^="#"]').forEach(function (a) {{ a.addEventListener('click', close); }});
}})();

document.querySelectorAll('[data-copy]').forEach(function (btn) {{
  btn.addEventListener('click', function () {{
    navigator.clipboard.writeText(btn.dataset.copy).then(function () {{
      var lbl = btn.querySelector('.lbl') || btn;
      var old = lbl.textContent;
      lbl.textContent = 'Kopirano!';
      setTimeout(function () {{ lbl.textContent = old; }}, 1800);
    }});
  }});
}});
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)

    try:
        holidays = parse_holidays(http_text(HOLIDAYS_ICS))
    except Exception as exc:  # kalendar praznika je pomocni izvor
        print(f"upozorenje: kalendar praznika nije dostupan ({exc})")
        holidays = []

    term_start, term_end = term_bounds(holidays)
    closed = no_school_days(holidays, term_start, term_end)

    statutory: dict[date, str] = {}
    for year in range(term_start.year, term_end.year + 2):
        statutory.update(statutory_holidays(year))
    for day, name in statutory.items():
        if term_start <= day <= term_end and day.weekday() <= 4:
            closed.setdefault(day, name)

    variants = build_variants(term_start, term_end)

    lessons = expand(variants, term_start, term_end, closed)
    events = lessons + holiday_events(holidays, statutory, term_start, term_end)

    status_path = DATA / "status.json"
    previous = json.loads(status_path.read_text(encoding="utf-8")) if status_path.exists() else {}

    fingerprint = hashlib.sha256(
        json.dumps(
            [
                [e.uid, e.summary, e.start.isoformat(), e.end.isoformat(),
                 e.start_time, e.end_time, e.location, e.description, e.all_day]
                for e in sorted(events, key=lambda e: e.uid)
            ],
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()

    now = datetime.now(timezone.utc)
    changed = fingerprint != previous.get("fingerprint")
    stamp = now.strftime("%Y%m%dT%H%M%SZ") if changed else previous.get(
        "ics_stamp", now.strftime("%Y%m%dT%H%M%SZ")
    )
    sequence = previous.get("sequence", 0) + 1 if changed else previous.get("sequence", 0)
    changed_at = now.isoformat(timespec="seconds") if changed else previous.get(
        "changed_at", now.isoformat(timespec="seconds")
    )

    cal_name = f"LINIGRA {CLASS_NAME} · raspored {SCHOOL_YEAR_START}./{SCHOOL_YEAR_START + 1}."
    (DOCS / ICS_NAME).write_text(
        render_ics(events, stamp, sequence, cal_name), encoding="utf-8", newline=""
    )
    write_csv(events, DOCS / CSV_NAME)

    school_days = len({e.start for e in lessons})
    fmt = lambda d: d.strftime("%d. %m. %Y.")
    milestones = [(fmt(term_start), "prvi dan nastave"), (fmt(term_end), "zadnji dan 1. polugodišta")]
    for ev in sorted((e for e in events if e.all_day), key=lambda e: e.start):
        if ev.start <= term_end:
            continue
        span = fmt(ev.start) if ev.start == ev.end else f"{fmt(ev.start)} – {fmt(ev.end)}"
        milestones.append((span, ev.summary.replace(" – nema nastave", "")))

    ctx = {
        "closed": closed,
        "milestones": milestones,
        "variants": variants,
        "lesson_count": len(lessons),
        "school_days": school_days,
        "term_start": term_start,
        "term_end": term_end,
        "week_html": weekly_table_html(variants[-1]),
        "checked_at": now.strftime("%d. %m. %Y. %H:%M UTC"),
        "changed_at": datetime.fromisoformat(changed_at).strftime("%d. %m. %Y. %H:%M UTC"),
    }
    (DOCS / "index.html").write_text(render_html(ctx), encoding="utf-8", newline="\n")

    status = {
        "fingerprint": fingerprint,
        "ics_stamp": stamp,
        "sequence": sequence,
        "changed_at": changed_at,
        "checked_at": now.isoformat(timespec="seconds"),
        "class": CLASS_NAME,
        "term_start": term_start.isoformat(),
        "term_end": term_end.isoformat(),
        "lesson_events": len(lessons),
        "holiday_events": len(events) - len(lessons),
        "school_days": school_days,
        "no_school_days": {d.isoformat(): n for d, n in sorted(closed.items())},
        "timetables": [
            {
                "tt_num": v.tt_num,
                "label": v.label,
                "valid_from": v.valid_from.isoformat(),
                "valid_to": v.valid_to.isoformat(),
                "weekly_blocks": len(v.blocks),
            }
            for v in variants
        ],
    }
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )

    print(
        f"{'PROMJENA' if changed else 'bez promjene'} · "
        f"{len(lessons)} nastavnih + {len(events) - len(lessons)} cjelodnevnih upisa · "
        f"{school_days} nastavnih dana · {term_start} → {term_end}"
    )


if __name__ == "__main__":
    main()
