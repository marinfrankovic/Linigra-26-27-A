"""Provjerava je li objavljena verzija na GitHub Pagesu usklađena s očekivanim sadržajem."""

import io
import re
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "https://marinfrankovic.github.io/Linigra-26-27-A/"


def get(path=""):
    return urllib.request.urlopen(BASE + path).read()


page = get().decode("utf-8")
print("--- stranica ---")
for pat in (
    "Važni datumi",
    "Blagdani koji padaju na nastavni dan",
    "naziv predmeta i ime nastavnika",
    "Dodaj u svoj kalendar",
    "Microsoft 365",
    "Apple Kalendar",
):
    print("  ", "OK  " if pat in page else "NEMA", pat)

cell = re.search(r"<span class='s'>(.*?)</span><span class='m'>(.*?)</span>", page)
if cell:
    print("   primjer u tjednom prikazu:", cell.group(1), "|", cell.group(2))

ics = get("linigra-1a.ics").decode("utf-8")
events = ics.split("BEGIN:VEVENT")[1:]
print("\n--- kalendar (.ics) ---")
print("   VEVENT:", len(events))
for line in events[1].strip().split("\r\n"):
    if line.startswith(("SUMMARY", "DESCRIPTION", "LOCATION")):
        print("  ", line)
body = ics.split("BEGIN:VEVENT", 1)[1]
print("   spominje li LINIGRA u dogadajima:", "LINIGRA" in body)
print("   spominje li 'Ucionica':", "Učionica" in body)

csv_text = get("linigra-1a.csv").decode("utf-8-sig")
print("\n--- CSV ---")
print("  ", csv_text.splitlines()[1])
