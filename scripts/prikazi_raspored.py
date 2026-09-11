"""Ispisuje trenutno stanje generiranog kalendara i tjedni raspored po danima."""

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from build import CLASS_NAME, DAY_NAMES_HR, build_variants, term_bounds  # noqa: E402
from build import HOLIDAYS_ICS, cached, http_text, parse_holidays  # noqa: E402

status = json.loads((Path(__file__).resolve().parent.parent / "docs/data/status.json").read_text("utf-8"))
print("verzije rasporeda na EduPageu:")
for t in status["timetables"]:
    print(
        f"  #{t['tt_num']:>3}  {t['valid_from']} -> {t['valid_to']}"
        f"  blokova/tjedno: {t['weekly_blocks']}   {t['label']}"
    )
print(f"\nnastavnih upisa: {status['lesson_events']} | nastavnih dana: {status['school_days']}")
print(f"razdoblje: {status['term_start']} -> {status['term_end']}\n")

holidays = parse_holidays(cached("skolski-praznici.json", lambda: {"ics": http_text(HOLIDAYS_ICS)})["ics"])
start, end = term_bounds(holidays)
for variant in build_variants(start, end):
    print(f"=== raspored #{variant.tt_num}  ({variant.valid_from} -> {variant.valid_to})")
    per_day = {}
    for b in variant.blocks:
        per_day.setdefault(b.weekday, []).append(b)
    for wd in range(5):
        print(f"  {DAY_NAMES_HR[wd]}")
        for b in sorted(per_day.get(wd, []), key=lambda x: x.start):
            teachers = ", ".join(b.lesson.teachers) or "-"
            print(f"    {b.start}-{b.end}  {b.lesson.subject}  ({teachers})")
    print()
