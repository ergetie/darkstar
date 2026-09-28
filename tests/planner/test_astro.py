import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import pytz
from astral.sun import sun

from backend.astro import SunCalculator


class TestSunCalculator(unittest.TestCase):
    def setUp(self):
        # Stockholm coordinates
        self.lat = 59.3293
        self.lon = 18.0686
        self.tz = "Europe/Stockholm"
        self.astro = SunCalculator(self.lat, self.lon, self.tz)

    def test_summer_day(self):
        # June 21st (Summer Solstice) - Sun should be up for a long time
        dt_noon = datetime(2024, 6, 21, 12, 0, 0, tzinfo=pytz.timezone(self.tz))
        self.assertTrue(self.astro.is_sun_up(dt_noon))

        # 3 AM might be twilight or sun up in Stockholm summer?
        # Sunrise is around 3:30 AM.
        datetime(2024, 6, 21, 3, 0, 0, tzinfo=pytz.timezone(self.tz))
        # With 30 min buffer, it might be close.

        # Midnight is definitely dark
        dt_midnight = datetime(2024, 6, 21, 0, 0, 0, tzinfo=pytz.timezone(self.tz))
        self.assertFalse(self.astro.is_sun_up(dt_midnight))

    def test_winter_day(self):
        # Dec 21st (Winter Solstice) - Short day
        dt_noon = datetime(2024, 12, 21, 12, 0, 0, tzinfo=pytz.timezone(self.tz))
        self.assertTrue(self.astro.is_sun_up(dt_noon))

        # 8 AM is dark in Stockholm winter (Sunrise ~8:45)
        dt_morning = datetime(2024, 12, 21, 8, 0, 0, tzinfo=pytz.timezone(self.tz))
        self.assertFalse(self.astro.is_sun_up(dt_morning, buffer_minutes=0))

        # 3 PM is dark in Stockholm winter (Sunset ~14:48)
        dt_afternoon = datetime(2024, 12, 21, 15, 30, 0, tzinfo=pytz.timezone(self.tz))
        self.assertFalse(self.astro.is_sun_up(dt_afternoon, buffer_minutes=0))

    def test_buffer(self):
        # Check buffer logic
        # Pick a time just after sunset
        dt = datetime(2024, 12, 21, 15, 0, 0, tzinfo=pytz.timezone(self.tz))
        # Sunset is approx 14:48. 15:00 is after sunset.

        # Without buffer, should be False
        self.assertFalse(self.astro.is_sun_up(dt, buffer_minutes=0))

        # With 30 min buffer, should be True (14:48 + 30m = 15:18)
        self.assertTrue(self.astro.is_sun_up(dt, buffer_minutes=30))

    def test_week_of_slots_matches_uncached_calculation(self):
        tz = pytz.timezone(self.tz)
        start = tz.localize(datetime(2024, 3, 28, 0, 0))  # spans the DST switch
        for i in range(7 * 96):
            dt = tz.normalize(start + timedelta(minutes=15 * i))
            s = sun(self.astro.location.observer, date=dt, tzinfo=tz)
            expected = (
                s["sunrise"] - timedelta(minutes=30) <= dt <= s["sunset"] + timedelta(minutes=30)
            )
            self.assertEqual(self.astro.is_sun_up(dt, buffer_minutes=30), expected, dt)

    def test_sun_times_computed_once_per_date(self):
        tz = pytz.timezone(self.tz)
        start = tz.localize(datetime(2024, 6, 1, 0, 0))
        with patch("backend.astro.sun", wraps=sun) as sun_spy:
            for i in range(2 * 96):
                self.astro.is_sun_up(start + timedelta(minutes=15 * i))
        self.assertEqual(sun_spy.call_count, 2)

    def test_failed_calculation_cached(self):
        with patch("backend.astro.sun", side_effect=ValueError("polar")) as sun_mock:
            dt = datetime(2024, 6, 21, 12, 0, 0, tzinfo=pytz.UTC)
            self.assertFalse(self.astro.is_sun_up(dt))
            self.assertFalse(self.astro.is_sun_up(dt + timedelta(hours=1)))
        self.assertEqual(sun_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
