"""Tests for get_profile_from_config's null/missing inverter_profile fallback
(fix-beta-monitor-false-alarms, spec: executor).
"""

import logging

from executor.profiles import get_profile_from_config


class TestNullInverterProfileFallsBackToGeneric:
    def test_null_inverter_profile_loads_generic_no_error_log(self, caplog):
        config = {"system": {"inverter_profile": None}}
        with caplog.at_level(logging.INFO, logger="executor.profiles"):
            profile = get_profile_from_config(config)

        assert profile is not None
        assert not any(r.levelno >= logging.ERROR for r in caplog.records)
        assert not any("None.yaml" in r.message for r in caplog.records)

    def test_missing_inverter_profile_key_loads_generic_no_error_log(self, caplog):
        config = {"system": {}}
        with caplog.at_level(logging.INFO, logger="executor.profiles"):
            get_profile_from_config(config)

        assert not any(r.levelno >= logging.ERROR for r in caplog.records)
        assert not any("None.yaml" in r.message for r in caplog.records)

    def test_empty_string_inverter_profile_loads_generic_no_error_log(self, caplog):
        config = {"system": {"inverter_profile": ""}}
        with caplog.at_level(logging.INFO, logger="executor.profiles"):
            get_profile_from_config(config)

        assert not any(r.levelno >= logging.ERROR for r in caplog.records)


class TestMisspelledProfileStillWarns:
    def test_misspelled_profile_name_logs_warning_and_falls_back(self, caplog):
        config = {"system": {"inverter_profile": "totally_not_a_real_profile"}}
        with caplog.at_level(logging.INFO, logger="executor.profiles"):
            profile = get_profile_from_config(config)

        assert any(
            r.levelno == logging.WARNING and "not found" in r.message for r in caplog.records
        )
        assert profile is not None


class TestExplicitlyConfiguredProfileLoadsNormally:
    def test_deye_profile_loads_without_warning_or_error(self, caplog):
        config = {"system": {"inverter_profile": "deye"}}
        with caplog.at_level(logging.INFO, logger="executor.profiles"):
            profile = get_profile_from_config(config)

        assert profile.metadata.name == "deye"
        assert not any(r.levelno >= logging.WARNING for r in caplog.records)
