from datetime import datetime, timedelta
from typing import Optional, Tuple
import pytz
from astral import LocationInfo
from astral.sun import sun
from astral.location import Location

class SunCalculator:
    def __init__(self, latitude: float, longitude: float, timezone: str = "Europe/Stockholm"):
        self.latitude = latitude
        self.longitude = longitude
        self.timezone = timezone
        self.location = LocationInfo(
            name="Darkstar Location",
            region="Region",
            timezone=timezone,
            latitude=latitude,
            longitude=longitude
        )

    def get_sun_times(self, date: datetime) -> Optional[Tuple[datetime, datetime]]:
        """
        Get sunrise and sunset for a specific date.
        Returns (sunrise, sunset) tuple or None if sun doesn't rise/set (polar day/night).
        """
        try:
            # astral expects a date object or datetime
            s = sun(self.location.observer, date=date, tzinfo=pytz.timezone(self.timezone))
            return s["sunrise"], s["sunset"]
        except Exception:
            # Handle edge cases like polar night/day if astral raises exceptions
            # (Though astral usually handles this, good to be safe)
            return None

    def is_sun_up(self, dt: datetime, buffer_minutes: int = 30) -> bool:
        """
        Check if sun is up at a specific datetime.
        
        Args:
            dt: The datetime to check (should be timezone aware or assume self.timezone)
            buffer_minutes: Minutes to extend the day (positive) or shrink it (negative).
                           Positive buffer means "sun is up" starts earlier and ends later.
                           Useful to capture twilight generation.
        """
        if dt.tzinfo is None:
            dt = pytz.timezone(self.timezone).localize(dt)
        
        times = self.get_sun_times(dt)
        if not times:
            # Fallback or polar handling. 
            # For now, assume if we can't calc sun, it's probably dark or something extreme.
            # But actually astral returns valid dict even for polar, just might be weird.
            # Let's assume false if failure to be safe for PV.
            return False
            
        sunrise, sunset = times
        
        # Apply buffer
        # "Sun is up" if current time is between (sunrise - buffer) and (sunset + buffer)
        effective_sunrise = sunrise - timedelta(minutes=buffer_minutes)
        effective_sunset = sunset + timedelta(minutes=buffer_minutes)
        
        return effective_sunrise <= dt <= effective_sunset
