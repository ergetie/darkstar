import unittest
from datetime import datetime
import pytz
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
        dt_early = datetime(2024, 6, 21, 3, 0, 0, tzinfo=pytz.timezone(self.tz))
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

if __name__ == '__main__':
    unittest.main()
