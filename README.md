# Raspored 1.A · LINIGRA 2026./2027.

Javni kalendar rasporeda razreda **1.A** u školi
[LINIGRA](https://linigra.edupage.org/timetable/), Gjure Szaba 4, Zagreb.

**Stranica:** <https://marinfrankovic.github.io/Linigra-26-27-A/>
**Kalendar za pretplatu:** `https://marinfrankovic.github.io/Linigra-26-27-A/linigra-1a.ics`

Pretplatiš se jednom, a kalendar se sam osvježava. Ako škola objavi novi raspored,
promjena stigne u Google Kalendar, Apple Kalendar ili Outlook bez ikakve akcije.

## Kako radi

1. `scripts/build.py` čita raspored s EduPage aSc API-ja i praznike iz javnog
   kalendara *Školski praznici HR*.
2. Iz toga gradi `docs/linigra-1a.ics` (pretplata), `docs/linigra-1a.csv`
   (jednokratni uvoz u klasični Outlook), `docs/index.html` i `docs/data/status.json`.
3. GitHub Actions to pokreće **ponedjeljkom i srijedom u 05:00 UTC** te ručno preko
   *Run workflow*. Ako se sadržaj promijenio, commita se novi ICS i objavljuje na
   GitHub Pages.

Prvi nastavni dan, kraj polugodišta i neradni dani ne upisuju se ručno nego se čitaju
iz kalendara praznika, pa se i to samo ispravi ako se promijeni.

## Detalji kalendara

- Razdoblje: 1. polugodište, 7. 9. 2026. – 23. 12. 2026.
- Praznici i blagdani su cjelodnevni događaji označeni kao slobodno vrijeme i tada
  nastave nema.
- Bez podsjetnika (reminders).
- Susjedni satovi istog predmeta spajaju se u jedan upis samo ako je pauza ≤ 10 min,
  pa velika pauza 12:05–12:35 ostaje slobodna.
- UID-ovi događaja su stabilni, pa osvježavanje mijenja postojeće upise umjesto da
  stvara duplikate.

## Lokalno pokretanje

```bash
python scripts/build.py
```

Bez vanjskih Python paketa. Bazni URL se može promijeniti preko `SITE_BASE_URL`, a
razred preko `LINIGRA_CLASS` (zadano `1.A`).

## Napomena

Neslužbeni kalendar. Službeni izvor je EduPage stranica škole i on ima prednost.
