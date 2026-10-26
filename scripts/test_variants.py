import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import build


class VariantActivationTests(unittest.TestCase):
    def setUp(self):
        self.term_start = date(2026, 9, 7)
        self.term_end = date(2026, 12, 23)
        self.listing = [
            {"tt_num": "25", "datefrom": "2026-10-12"},
            {"tt_num": "26", "datefrom": "2026-10-26"},
            {"tt_num": "27", "datefrom": "2026-11-02"},
        ]

    def variants_on(self, today):
        with (
            patch.object(build, "fetch_variants", return_value=self.listing),
            patch.object(build, "fetch_tables", return_value={}) as fetch,
            patch.object(build, "weekly_blocks", return_value=({}, [])),
        ):
            variants = build.build_variants(self.term_start, self.term_end, today)
        self.assertEqual(fetch.call_count, len(variants))
        return variants

    def test_future_versions_are_not_published(self):
        for today, expected in [
            (date(2026, 10, 25), ["25"]),
            (date(2026, 10, 26), ["25", "26"]),
            (date(2026, 11, 1), ["25", "26"]),
            (date(2026, 11, 2), ["25", "26", "27"]),
        ]:
            with self.subTest(today=today):
                variants = self.variants_on(today)
                self.assertEqual([variant.tt_num for variant in variants], expected)
                self.assertEqual(variants[-1].valid_to, self.term_end)
                for previous, current in zip(variants, variants[1:]):
                    self.assertEqual((current.valid_from - previous.valid_to).days, 1)

    def test_activation_uses_zagreb_date(self):
        instant = datetime(2026, 11, 1, 23, 5, tzinfo=timezone.utc)
        today = instant.astimezone(ZoneInfo(build.TIMEZONE_ID)).date()
        self.assertEqual(today, date(2026, 11, 2))
        self.assertEqual(self.variants_on(today)[-1].tt_num, "27")

    def test_ics_and_html_activate_the_same_version(self):
        def blocks_for(number):
            lesson = build.Lesson("Subject " + number, number, [], [], [])
            return {}, [build.Block(0, "08:45", "09:30", [1], lesson)]

        for today, expected, excluded in [
            (date(2026, 10, 26), "26", "27"),
            (date(2026, 11, 2), "27", "26"),
        ]:
            with (
                self.subTest(today=today),
                patch.object(build, "fetch_variants", return_value=self.listing),
                patch.object(build, "fetch_tables", side_effect=lambda number: number),
                patch.object(build, "weekly_blocks", side_effect=blocks_for),
            ):
                variants = build.build_variants(self.term_start, self.term_end, today)
                events = build.expand(variants, today, self.term_end, {})
                ics = build.render_ics(events, "20261026T000000Z", 1, "Test")
                html = build.weekly_table_html(variants[-1])
                for output in (ics, html):
                    self.assertIn("Subject " + expected, output)
                    self.assertNotIn("Subject " + excluded, output)

    def test_no_effective_version_stops_generation(self):
        with self.assertRaises(SystemExit):
            self.variants_on(date(2026, 10, 11))


if __name__ == "__main__":
    unittest.main()