"""Provjerava da assert_clean_utf8 stvarno prijavi pokvareno kodiranje."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build import assert_clean_utf8  # noqa: E402

target = Path(__file__).resolve().parent.parent / "docs" / "index.html"
original = target.read_bytes()

# Simuliraj UTF-8 tekst procitan kao latin-1 pa opet zapisan kao UTF-8.
broken = original.replace(
    "Njemački".encode("utf-8"),
    "Njemački".encode("utf-8").decode("latin-1").encode("utf-8"),
)
assert broken != original, "test nije uspio pokvariti sadrzaj"

try:
    target.write_bytes(broken)
    try:
        assert_clean_utf8(target)
    except SystemExit as exc:
        print("OK - mojibake uhvacen:", exc)
    else:
        print("PROBLEM - mojibake nije uhvacen")
        sys.exit(1)
finally:
    target.write_bytes(original)
    print("original vracen:", target.read_bytes() == original)
