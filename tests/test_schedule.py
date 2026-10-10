import unittest
from datetime import date, datetime, time, timedelta, timezone

from spory.schedule import OneTimeDeadline, Schedule, WeeklyRule, format_weekdays, parse_weekdays

UTC = timezone.utc


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        # Friday 2026-10-02 08:00
        self.now = datetime(2026, 10, 2, 8, 0, tzinfo=UTC)
        self.rule = WeeklyRule(parse_weekdays("mon-fri"), time(9, 30))

    def test_parse_weekdays(self):
        self.assertEqual(parse_weekdays("weekdays"), frozenset(range(5)))
        self.assertEqual(parse_weekdays("sat,sun"), frozenset({5, 6}))
        self.assertEqual(parse_weekdays("fri-mon"), frozenset({4, 5, 6, 0}))
        self.assertEqual(format_weekdays(parse_weekdays("Monday-Friday")), "mon-fri")
        with self.assertRaises(ValueError):
            parse_weekdays("someday")

    def test_next_weekly_deadline_today(self):
        s = Schedule(weekly=[self.rule], tz=UTC)
        self.assertEqual(s.next_deadline(self.now).at, datetime(2026, 10, 2, 9, 30, tzinfo=UTC))

    def test_skips_weekend_and_skip_dates(self):
        s = Schedule(weekly=[self.rule], skip_dates={date(2026, 10, 5)}, tz=UTC)
        after = self.now.replace(hour=10)
        self.assertEqual(s.next_deadline(after).at, datetime(2026, 10, 6, 9, 30, tzinfo=UTC))

    def test_one_time_wins_when_earlier(self):
        once = OneTimeDeadline(self.now + timedelta(minutes=45), 90)
        s = Schedule(weekly=[self.rule], one_time=[once], tz=UTC)
        d = s.next_deadline(self.now)
        self.assertEqual((d.at, d.target_percent, d.source), (once.at, 90, "one-time"))

    def test_empty(self):
        self.assertIsNone(Schedule(tz=UTC).next_deadline(self.now))

    def test_prune(self):
        s = Schedule(
            one_time=[OneTimeDeadline(self.now - timedelta(hours=1))],
            skip_dates={date(2026, 10, 1), date(2026, 10, 2)},
            tz=UTC,
        )
        s.prune(self.now)
        self.assertEqual(s.one_time, [])
        self.assertEqual(s.skip_dates, {date(2026, 10, 2)})


if __name__ == "__main__":
    unittest.main()
