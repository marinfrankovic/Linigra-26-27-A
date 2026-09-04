"""Provjera hrvatskih dijakritika u objavljenim kalendarskim datotekama."""

import csv
import io
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BASE = "https://marinfrankovic.github.io/Linigra-26-27-A/"
DIACRITICS = "čćžšđČĆŽŠĐ"


def fetch(path):
    with urllib.request.urlopen(BASE + path) as resp:
        return resp.read(), dict(resp.headers)


def unfold(text):
    return text.replace("\r\n ", "").replace("\r\n\t", "")


ok = True

# --- ICS ---------------------------------------------------------------- #
raw, headers = fetch("linigra-1a.ics")
print("--- linigra-1a.ics ---")
print("   Content-Type:", headers.get("Content-Type"))
print("   BOM:", raw[:3] == b"\xef\xbb\xbf")

try:
    text = raw.decode("utf-8", errors="strict")
    print("   strogi UTF-8 dekod: OK")
except UnicodeDecodeError as exc:
    ok = False
    print("   strogi UTF-8 dekod: PAO ->", exc)
    raise SystemExit(1)

if raw.decode("utf-8").encode("utf-8") != raw:
    ok = False
    print("   round-trip: PAO")

flat = unfold(text)
found = sorted({c for c in flat if c in DIACRITICS})
print("   pronadeni dijakritici:", "".join(found) or "(nijedan)")

expected = [
    "SUMMARY:Njemački jezik u turizmu",
    "SUMMARY:Zaštita na radu u turizmu i ugostiteljstvu",
    "SUMMARY:Sat razredne zajednice",
    "DESCRIPTION:Žaneta Štrbac Mišić",
    "DESCRIPTION:Sandra Bučić Srdarev",
    "DESCRIPTION:Marina Šušić",
    "DESCRIPTION:Iva Rončević",
    "DESCRIPTION:Lana Potočki",
    "DESCRIPTION:Marija Erić",
    "DESCRIPTION:Trpimir-Frane Sulić",
    "SUMMARY:Dan sjećanja na žrtve Domovinskog rata – nema nastave",
    "SUMMARY:🎉 Prvi dan škole",
]
for e in expected:
    hit = e in flat
    ok &= hit
    print("   ", "OK  " if hit else "NEMA", e)

# Mojibake tragovi (UTF-8 procitan kao latin-1) i zamjenski znakovi.
for bad in ("Ä", "Å¡", "Å¾", "Ã", "\ufffd", "?ivogo"):
    if bad in flat:
        ok = False
        print("    MOJIBAKE:", repr(bad))

longest = max(len(line.encode("utf-8")) for line in text.split("\r\n"))
print("   najduza linija:", longest, "okteta", "(<=75 OK)" if longest <= 75 else "(PREDUGA)")
for line in text.split("\r\n"):
    if line.startswith(" "):
        continue
    if line and ":" not in line and ";" not in line:
        ok = False
        print("    sumnjiv redak:", repr(line[:60]))

# --- CSV ---------------------------------------------------------------- #
raw, headers = fetch("linigra-1a.csv")
print("\n--- linigra-1a.csv ---")
print("   Content-Type:", headers.get("Content-Type"))
print("   BOM:", raw[:3] == b"\xef\xbb\xbf", "(Excel/Outlook trebaju BOM)")
try:
    csv_text = raw.decode("utf-8-sig", errors="strict")
    print("   strogi UTF-8 dekod: OK")
except UnicodeDecodeError as exc:
    ok = False
    print("   strogi UTF-8 dekod: PAO ->", exc)
    raise SystemExit(1)

rows = list(csv.DictReader(io.StringIO(csv_text)))
subjects = sorted({r["Subject"] for r in rows})
teachers = sorted({r["Description"] for r in rows if r["All day event"] == "False"})
print("   redaka:", len(rows))
print("   predmeti:")
for s in subjects:
    print("     ", s)
print("   nastavnici:")
for t in teachers:
    print("     ", t)
for bad in ("Ä", "Å", "Ã", "\ufffd"):
    if bad in csv_text:
        ok = False
        print("    MOJIBAKE u CSV-u:", repr(bad))

print("\nZAKLJUCAK:", "sve OK" if ok else "IMA PROBLEMA")
sys.exit(0 if ok else 1)
