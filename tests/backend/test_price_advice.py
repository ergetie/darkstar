"""Tests for price advisor rules (price-alert-accuracy)."""

import unittest
from unittest.mock import AsyncMock, patch

from backend.api.routers.analyst import _get_price_advice, _get_strategy_advice


def _day(day_label, days_ahead, avg_spot_p50):
    return {"day_label": day_label, "days_ahead": days_ahead, "avg_spot_p50": avg_spot_p50}


class TestGetPriceAdviceRule1(unittest.TestCase):
    """Rule 1: cheapest day ahead (price-alert-accuracy 3.1)."""

    def test_fires_on_relative_and_absolute_drop(self):
        """Fires when a day is >=30% AND >=0.15 SEK/kWh below today's actual average."""
        print("\n--- Rule 1: fires on relative + absolute drop ---")

        daily_outlook = [_day("Mon", 1, 0.3), _day("Tue", 2, 0.5)]
        today_avg = 0.5  # Monday: 40% and 0.20 SEK below

        result = _get_price_advice(daily_outlook, today_avg, None, None)

        cheapest_rules = [r for r in result if "drop" in r["message"].lower()]
        self.assertEqual(len(cheapest_rules), 1)
        self.assertEqual(cheapest_rules[0]["category"], "price")
        self.assertIn("Mon", cheapest_rules[0]["message"])
        self.assertIn("40%", cheapest_rules[0]["message"])

        print("✓ Rule 1 fires on a genuine relative+absolute drop")

    def test_suppressed_when_relative_only_tiny_absolute(self):
        """Suppressed when the relative drop is >=30% but the absolute drop is <0.15 SEK/kWh."""
        print("\n--- Rule 1: suppressed for relative-only tiny absolute drop ---")

        # 30%+ relative drop, but at a low price level the absolute drop is tiny
        today_avg = 0.20
        daily_outlook = [_day("Mon", 1, 0.13)]  # 35% relative drop, only 0.07 SEK absolute

        result = _get_price_advice(daily_outlook, today_avg, None, None)

        cheapest_rules = [r for r in result if "drop" in r["message"].lower()]
        self.assertEqual(len(cheapest_rules), 0)

        print("✓ Rule 1 suppressed when absolute drop is below 0.15 SEK/kWh")

    def test_suppressed_when_absolute_only_below_relative_threshold(self):
        """Suppressed when the absolute drop is >=0.15 SEK/kWh but relative drop is <30%."""
        print("\n--- Rule 1: suppressed for absolute-only below relative threshold ---")

        today_avg = 1.0
        daily_outlook = [_day("Mon", 1, 0.80)]  # 0.20 SEK absolute drop, only 20% relative

        result = _get_price_advice(daily_outlook, today_avg, None, None)

        cheapest_rules = [r for r in result if "drop" in r["message"].lower()]
        self.assertEqual(len(cheapest_rules), 0)

        print("✓ Rule 1 suppressed when relative drop is below 30%")


class TestGetPriceAdviceRule2(unittest.TestCase):
    """Rule 2: prices rising, regression guard against the D+1-as-today proxy bug."""

    def test_fires_against_real_today_average(self):
        """Fires when D+1..D+3 all exceed today's actual average (spec regression scenario)."""
        print("\n--- Rule 2: fires against the real today average ---")

        today_avg = 0.50
        daily_outlook = [_day("Mon", 1, 0.6), _day("Tue", 2, 0.7), _day("Wed", 3, 0.8)]

        result = _get_price_advice(daily_outlook, today_avg, None, None)

        rising_rules = [r for r in result if "rising" in r["message"].lower()]
        self.assertEqual(len(rising_rules), 1)
        self.assertIn("cheapest day", rising_rules[0]["message"].lower())

        print("✓ Rule 2 fires — impossible under the former D+1-as-today proxy")

    def test_does_not_fire_when_not_all_higher(self):
        """Does not fire when one of D+1..D+3 is not above today's average."""
        print("\n--- Rule 2: does not fire when not all days are higher ---")

        today_avg = 0.50
        daily_outlook = [_day("Mon", 1, 0.6), _day("Tue", 2, 0.4), _day("Wed", 3, 0.8)]

        result = _get_price_advice(daily_outlook, today_avg, None, None)

        rising_rules = [r for r in result if "rising" in r["message"].lower()]
        self.assertEqual(len(rising_rules), 0)

        print("✓ Rule 2 does not fire when D+1..D+3 are not all higher")


class TestGetPriceAdviceRule3(unittest.TestCase):
    """Rule 3: cheap overnight window / solar midday fallback."""

    def test_fires_on_genuinely_cheap_overnight_window(self):
        """Fires when the real overnight window average is >=25% below D+1's daily average."""
        print("\n--- Rule 3: fires on genuinely cheap overnight window ---")

        daily_outlook = [_day("Mon", 1, 0.5)]
        # Overnight window average is 30% below D+1's daily average
        result = _get_price_advice(daily_outlook, 0.5, overnight_avg=0.35, midday_avg=None)

        overnight_rules = [r for r in result if "tonight" in r["message"].lower()]
        self.assertEqual(len(overnight_rules), 1)
        self.assertIn("22:00-06:00", overnight_rules[0]["message"])

        print("✓ Rule 3 fires on a genuinely cheap overnight window")

    def test_single_cheap_slot_does_not_fire_overnight(self):
        """Regression guard: a single cheap slot must not trigger the overnight message.

        The old min-slot heuristic fired on 96% of replayed days off a single deep dip;
        the window average is what must qualify now.
        """
        print("\n--- Rule 3: single cheap slot regression guard ---")

        daily_outlook = [_day("Mon", 1, 0.5)]
        # Overnight window average only 10% below — does not qualify, even though some
        # individual slot within it might be much cheaper (not modeled here at all,
        # since the rule no longer looks at any single-slot minimum).
        result = _get_price_advice(daily_outlook, 0.5, overnight_avg=0.45, midday_avg=None)

        overnight_rules = [r for r in result if "tonight" in r["message"].lower()]
        self.assertEqual(len(overnight_rules), 0)

        print("✓ Rule 3 does not fire from a single cheap slot — window average must qualify")

    def test_summer_solar_fixture_emits_midday_only(self):
        """When overnight doesn't qualify but midday does, emit the solar-midday message only."""
        print("\n--- Rule 3: summer solar fixture emits midday message only ---")

        daily_outlook = [_day("Mon", 1, 0.5)]
        # Overnight only 4% below (does not qualify); midday 40% below (qualifies)
        result = _get_price_advice(daily_outlook, 0.5, overnight_avg=0.48, midday_avg=0.30)

        overnight_rules = [r for r in result if "tonight" in r["message"].lower()]
        midday_rules = [r for r in result if "midday" in r["message"].lower()]

        self.assertEqual(len(overnight_rules), 0)
        self.assertEqual(len(midday_rules), 1)
        self.assertIn("solar", midday_rules[0]["message"].lower())

        print("✓ Summer solar fixture emits the midday message and no overnight message")

    def test_neither_window_qualifies(self):
        """No Rule 3 advice when neither window is cheap enough."""
        print("\n--- Rule 3: neither window qualifies ---")

        daily_outlook = [_day("Mon", 1, 0.5)]
        result = _get_price_advice(daily_outlook, 0.5, overnight_avg=0.48, midday_avg=0.47)

        window_rules = [r for r in result if "tonight" in r["message"].lower() or "midday" in r["message"].lower()]
        self.assertEqual(len(window_rules), 0)

        print("✓ No overnight/midday advice when neither window qualifies")


class TestGetPriceAdviceEdgeCases(unittest.TestCase):
    def test_no_advice_when_thresholds_not_met(self):
        """No advice at all when no rule's thresholds are met."""
        print("\n--- Testing No Advice When Thresholds Not Met ---")

        daily_outlook = [_day("Mon", 1, 0.48)]
        result = _get_price_advice(daily_outlook, 0.5, overnight_avg=0.47, midday_avg=None)

        self.assertEqual(len(result), 0)

        print("✓ No advice when thresholds not met")

    def test_empty_output_when_no_data(self):
        """Test empty output when daily_outlook is empty."""
        print("\n--- Testing Empty Output ---")

        result = _get_price_advice([], 0.5, None, None)

        self.assertEqual(len(result), 0)

        print("✓ Empty output when no data")


class TestStrategyAdviceIntegration(unittest.IsolatedAsyncioTestCase):
    """Test integration of price advice into strategy advice, incl. degradation paths."""

    @patch("backend.api.routers.analyst.load_yaml")
    @patch("backend.core.price_outlook.get_price_window_averages")
    @patch("backend.api.routers.analyst._get_today_avg_spot_price", new_callable=AsyncMock)
    @patch("backend.core.price_outlook.get_daily_outlook")
    @patch("backend.core.forecasts.get_forecast_db_path")
    async def test_price_advice_appended_to_existing(
        self, mock_get_db_path, mock_get_outlook, mock_today_avg, mock_get_windows, mock_load_config
    ):
        """Test price advice is appended to existing advice items."""
        print("\n--- Testing Price Advice Appended to Existing ---")

        mock_load_config.return_value = {
            "price_forecast": {"enabled": True},
            "s_index": {"risk_appetite": 5},  # Will trigger risk advice
            "timezone": "Europe/Stockholm",
        }

        mock_get_outlook.return_value = [_day("Mon", 1, 0.3)]
        mock_today_avg.return_value = 0.5
        mock_get_windows.return_value = {"overnight_avg": None, "midday_avg": None}

        result = await _get_strategy_advice()

        categories = [item["category"] for item in result["advice"]]

        self.assertIn("risk", categories)
        self.assertIn("price", categories)

        print("✓ Price advice appended to existing advice")

    @patch("backend.api.routers.analyst.load_yaml")
    async def test_existing_advice_unchanged_when_forecast_disabled(self, mock_load_config):
        """Test existing advice unchanged when price forecast disabled."""
        print("\n--- Testing Existing Advice Unchanged When Disabled ---")

        mock_load_config.return_value = {
            "price_forecast": {"enabled": False},
            "s_index": {"risk_appetite": 5},
        }

        result = await _get_strategy_advice()

        categories = [item["category"] for item in result["advice"]]

        self.assertIn("risk", categories)
        self.assertNotIn("price", categories)

        print("✓ Existing advice unchanged when forecast disabled")

    @patch("backend.api.routers.analyst.load_yaml")
    @patch("backend.core.price_outlook.get_daily_outlook")
    @patch("backend.core.forecasts.get_forecast_db_path")
    async def test_no_price_advice_when_no_forecast_rows(
        self, mock_get_db_path, mock_get_outlook, mock_load_config
    ):
        """No price advice, other categories intact, when there are no forecast rows."""
        print("\n--- Testing No Forecast Rows ---")

        mock_load_config.return_value = {
            "price_forecast": {"enabled": True},
            "s_index": {"risk_appetite": 5},
        }
        mock_get_outlook.return_value = []

        result = await _get_strategy_advice()

        categories = [item["category"] for item in result["advice"]]

        self.assertIn("risk", categories)
        self.assertNotIn("price", categories)

        print("✓ No price advice when no forecast rows exist")

    @patch("backend.api.routers.analyst.load_yaml")
    @patch("backend.api.routers.analyst._get_today_avg_spot_price", new_callable=AsyncMock)
    @patch("backend.core.price_outlook.get_daily_outlook")
    @patch("backend.core.forecasts.get_forecast_db_path")
    async def test_no_price_advice_when_today_prices_unavailable(
        self, mock_get_db_path, mock_get_outlook, mock_today_avg, mock_load_config
    ):
        """Degradation: today's prices unavailable => no price items, other categories intact."""
        print("\n--- Testing Today's Prices Unavailable ---")

        mock_load_config.return_value = {
            "price_forecast": {"enabled": True},
            "s_index": {"risk_appetite": 5},
        }
        mock_get_outlook.return_value = [_day("Mon", 1, 0.3)]
        mock_today_avg.return_value = None

        result = await _get_strategy_advice()

        categories = [item["category"] for item in result["advice"]]

        self.assertIn("risk", categories)
        self.assertNotIn("price", categories)
        self.assertEqual(result.get("error"), None)

        print("✓ No price advice when today's actual prices are unavailable; other advice intact")


if __name__ == "__main__":
    unittest.main()
