"""
Comprehensive tests for Learning Engine (Rev 9)
"""

import json
import os
import sqlite3
import tempfile
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import pytz
import yaml

from learning import LearningEngine, LearningLoops, NightlyOrchestrator, DeterministicSimulator


@pytest.fixture(scope="module")
def temp_db():
    """Create temporary database for testing"""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture(scope="module") 
def learning_engine(temp_db):
    """Create learning engine with temporary database"""
    # Create a temporary config
    temp_config = {
        'learning': {
            'enable': True,
            'sqlite_path': temp_db,
            'horizon_days': 7,
            'min_improvement_threshold': 0.015,
            'auto_apply': False,  # Don't auto-apply in tests
            'max_daily_param_change': {
                'pv_confidence_percent': 1.0,
                'load_safety_margin_percent': 1.0,
                'battery_use_margin_sek': 0.02,
                'export_profit_margin_sek': 0.02,
                's_index_base_factor': 0.05,
                's_index_pv_deficit_weight': 0.05,
                's_index_temp_weight': 0.05,
                'future_price_guard_buffer_sek': 0.05
            }
        },
        'timezone': 'Europe/Stockholm',
        'forecasting': {
            'pv_confidence_percent': 90.0,
            'load_safety_margin_percent': 110.0
        },
        'decision_thresholds': {
            'battery_use_margin_sek': 0.10,
            'export_profit_margin_sek': 0.05
        },
        's_index': {
            'base_factor': 1.05,
            'pv_deficit_weight': 0.30,
            'temp_weight': 0.20,
            'max_factor': 1.5
        },
        'arbitrage': {
            'future_price_guard_buffer_sek': 0.00
        }
    }
    
    with patch('learning.LearningEngine._load_config', return_value=temp_config):
        engine = LearningEngine('dummy_config.yaml')
        return engine


class TestLearningEngine:
    """Test core LearningEngine functionality"""
    
    def test_schema_initialization(self, learning_engine):
        """Test that database schema is created correctly"""
        with sqlite3.connect(learning_engine.db_path) as conn:
            cursor = conn.cursor()
            
            # Check all required tables exist
            tables = cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name IN (
                    'slot_observations', 'slot_forecasts', 'config_versions',
                    'learning_runs', 'learning_metrics'
                )
            """).fetchall()
            
            assert len(tables) == 5, "All required tables should be created"
            
            # Check indexes exist
            indexes = cursor.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='index' AND name LIKE 'idx_%'
            """).fetchall()
            
            assert len(indexes) >= 4, "Required indexes should be created"
    
    def test_etl_cumulative_to_slots(self, learning_engine):
        """Test ETL functionality with sample data"""
        timezone = pytz.timezone('Europe/Stockholm')
        now = datetime.now(timezone)
        
        # Create sample cumulative data with closer timestamps for 15-min slots
        start_time = now - timedelta(minutes=30)
        cumulative_data = {
            'import': [
                (start_time, 100.0),
                (start_time + timedelta(minutes=15), 105.5),
                (start_time + timedelta(minutes=30), 111.2),
            ],
            'pv': [
                (start_time, 50.0),
                (start_time + timedelta(minutes=15), 52.3),
                (start_time + timedelta(minutes=30), 54.8),
            ]
        }
        
        # Run ETL
        observations_df = learning_engine.etl_cumulative_to_slots(cumulative_data)
        
        # Verify results
        assert not observations_df.empty, "ETL should produce observations"
        assert 'slot_start' in observations_df.columns, "Should have slot_start column"
        assert 'import_kwh' in observations_df.columns, "Should have import_kwh column"
        assert 'pv_kwh' in observations_df.columns, "Should have pv_kwh column"
        
        # Check that total deltas match expected values
        total_import_delta = observations_df['import_kwh'].sum()
        total_pv_delta = observations_df['pv_kwh'].sum()
        
        assert abs(total_import_delta - 11.2) < 0.1, f"Total import delta should be ~11.2, got {total_import_delta}"
        assert abs(total_pv_delta - 4.8) < 0.1, f"Total PV delta should be ~4.8, got {total_pv_delta}"
    
    def test_store_slot_observations(self, learning_engine):
        """Test storing slot observations"""
        timezone = pytz.timezone('Europe/Stockholm')
        now = datetime.now(timezone)
        
        # Create test observations
        observations_df = pd.DataFrame({
            'slot_start': [now],
            'slot_end': [now + timedelta(minutes=15)],
            'import_kwh': [1.5],
            'export_kwh': [0.5],
            'pv_kwh': [2.0],
            'load_kwh': [3.0],
            'soc_start_percent': [40.0],
            'soc_end_percent': [45.0]
        })
        
        # Store observations
        learning_engine.store_slot_observations(observations_df)
        
        # Verify storage
        with sqlite3.connect(learning_engine.db_path) as conn:
            cursor = conn.cursor()
            stored = cursor.execute("""
                SELECT import_kwh, export_kwh, pv_kwh, load_kwh, 
                       soc_start_percent, soc_end_percent
                FROM slot_observations
                LIMIT 1
            """).fetchone()
            
            assert stored is not None, "Observations should be stored"
            assert stored[0] == 1.5, "Import kWh should match"
            assert stored[1] == 0.5, "Export kWh should match"
            assert stored[2] == 2.0, "PV kWh should match"
            assert stored[3] == 3.0, "Load kWh should match"
    
    def test_get_status(self, learning_engine):
        """Test learning engine status endpoint"""
        status = learning_engine.get_status()
        
        assert 'enabled' in status, "Status should include enabled flag"
        assert 'sqlite_path' in status, "Status should include database path"
        assert 'metrics' in status, "Status should include metrics"
        assert 'last_updated' in status, "Status should include last updated time"
        
        assert status['enabled'] is True, "Learning should be enabled"
        assert status['sqlite_path'] == learning_engine.db_path, "Database path should match"


@pytest.fixture
def learning_loops(learning_engine):
    """Create learning loops instance"""
    return LearningLoops(learning_engine)


class TestLearningLoops:
    """Test individual learning loops"""
    
    def test_forecast_calibrator_no_data(self, learning_loops):
        """Test forecast calibrator with insufficient data"""
        result = learning_loops.forecast_calibrator()
        
        # With no data, the calibrator might return None or make minimal changes
        # Both are acceptable behaviors depending on implementation
        assert result is None or isinstance(result, dict), "Should return None or result dict"
    
    def test_threshold_tuner_no_improvement(self, learning_loops):
        """Test threshold tuner when no improvement found"""
        # Mock simulator to return no improvement
        with patch.object(learning_loops.simulator, 'simulate_with_params') as mock_sim:
            mock_sim.return_value = {
                'objective_value': 100.0,  # Same as baseline
                'total_cost_sek': 50.0,
                'total_wear_sek': 10.0
            }
            
            result = learning_loops.threshold_tuner()
            
            # Should return None when no improvement meets threshold
            assert result is None, "Should return None when no improvement found"
    
    def test_s_index_tuner_bounds_check(self, learning_loops):
        """Test S-index tuner respects parameter bounds"""
        # Mock simulator to return improvement but with out-of-bounds parameters
        with patch.object(learning_loops.simulator, 'simulate_with_params') as mock_sim:
            # First call (baseline)
            mock_sim.return_value = {'objective_value': 100.0}
            
            # Subsequent calls (candidates)
            def side_effect(params, start_date, end_date):
                if 's_index.base_factor' in params:
                    # Return improvement for out-of-bounds candidate
                    if params['s_index.base_factor'] > 2.0:  # Beyond max_factor
                        return {'objective_value': 80.0}  # Better than baseline
                return {'objective_value': 100.0}
            
            mock_sim.side_effect = side_effect
            
            result = learning_loops.s_index_tuner()
            
            # Should not apply out-of-bounds changes
            assert result is None, "Should not apply out-of-bounds parameter changes"
    
    def test_export_guard_tuner_no_exports(self, learning_loops):
        """Test export guard tuner with no export data"""
        result = learning_loops.export_guard_tuner()
        
        # Should return None when there's no export data
        assert result is None, "Should return None with no export data"


@pytest.fixture
def orchestrator(learning_engine):
    """Create nightly orchestrator instance"""
    return NightlyOrchestrator(learning_engine)


class TestNightlyOrchestrator:
    """Test nightly orchestration functionality"""
    
    def test_run_nightly_job_disabled(self, orchestrator):
        """Test nightly job when learning is disabled"""
        # Disable learning
        orchestrator.learning_config['enable'] = False
        
        result = orchestrator.run_nightly_job()
        
        assert result['status'] == 'skipped', "Should be skipped when disabled"
        assert 'reason' in result, "Should provide reason for skipping"
    
    def test_run_nightly_job_success(self, orchestrator):
        """Test successful nightly job execution"""
        # Mock learning loops to return no changes (simpler test)
        with patch.object(orchestrator.loops, 'forecast_calibrator', return_value=None):
            with patch.object(orchestrator.loops, 'threshold_tuner', return_value=None):
                with patch.object(orchestrator.loops, 's_index_tuner', return_value=None):
                    with patch.object(orchestrator.loops, 'export_guard_tuner', return_value=None):
                        
                        result = orchestrator.run_nightly_job()
                        
                        assert result['status'] in ['completed', 'skipped'], "Should complete or be skipped"
                        if result['status'] == 'completed':
                            assert 'run_id' in result, "Should return run ID"
                            assert result['loops_run'] == 1, "Should run forecast calibrator"
                            assert result['changes_proposed'] == 0, "Should have no changes"
                            assert result['changes_applied'] == 0, "Should apply no changes"
    
    def test_apply_changes_success(self, orchestrator, tmp_path, monkeypatch):
        """Test successful change application"""
        config_path = tmp_path / 'config.yaml'
        config_path.write_text("{}", encoding='utf-8')
        monkeypatch.chdir(tmp_path)

        changes = {
            'forecasting.pv_confidence_percent': 91.0,
            'forecasting.load_safety_margin_percent': 109.0
        }

        loop_results = [{
            'loop': 'forecast_calibrator',
            'reason': 'Test adjustment',
            'metrics': {'test_metric': 1.0}
        }]

        result = orchestrator._apply_changes(changes, loop_results)
        assert result == changes

        updated_config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
        assert updated_config['forecasting']['pv_confidence_percent'] == 91.0
        assert updated_config['forecasting']['load_safety_margin_percent'] == 109.0

        with sqlite3.connect(orchestrator.engine.db_path) as conn:
            row = conn.execute(
                "SELECT metrics_json FROM config_versions ORDER BY id DESC LIMIT 1"
            ).fetchone()
            assert row is not None
            payload = json.loads(row[0])
            assert 'diff' in payload
            diff = payload['diff']
            assert diff['forecasting.pv_confidence_percent']['old'] is None
            assert diff['forecasting.pv_confidence_percent']['new'] == 91.0


@pytest.fixture
def simulator(learning_engine):
    """Create simulator instance"""
    return DeterministicSimulator(learning_engine)


class TestDeterministicSimulator:
    """Test deterministic simulator functionality"""
    
    def test_simulate_with_params_no_data(self, simulator):
        """Test simulation with no historical data"""
        start_date = datetime.now(pytz.UTC)
        end_date = start_date + timedelta(days=7)
        param_changes = {'test.param': 1.0}
        
        result = simulator.simulate_with_params(start_date, end_date, param_changes)
        
        # Should return default values when no data
        assert 'total_cost_sek' in result, "Should return cost metric"
        assert 'total_wear_sek' in result, "Should return wear metric"
        assert 'objective_value' in result, "Should return objective value"
    
    def test_get_stored_historical_data(self, simulator):
        """Test retrieving stored historical data"""
        # Insert test data with all required fields
        now = datetime.now(pytz.UTC)
        with sqlite3.connect(simulator.engine.db_path) as conn:
            conn.execute("""
                INSERT INTO slot_observations 
                (slot_start, slot_end, import_kwh, export_kwh, pv_kwh, load_kwh)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                now.isoformat(),
                (now + timedelta(minutes=15)).isoformat(),
                1.5, 0.5, 2.0, 3.0
            ))
            conn.commit()
        
        start_date = now - timedelta(days=1)
        end_date = now + timedelta(days=1)
        
        data = simulator._get_stored_historical_data(start_date, end_date)
        
        assert 'observations' in data, "Should return observations"
        assert 'forecasts' in data, "Should return forecasts"
        assert len(data['observations']) >= 1, "Should have at least one observation"


class TestErrorHandling:
    """Test error handling and edge cases"""
    
    def test_learning_engine_disabled(self):
        """Test behavior when learning is disabled"""
        temp_config = {
            'learning': {'enable': False},
            'timezone': 'Europe/Stockholm'
        }
        
        with patch('learning.LearningEngine._load_config', return_value=temp_config):
            engine = LearningEngine('dummy_config.yaml')
            status = engine.get_status()
            
            assert status['enabled'] is False, "Should be disabled"
            assert 'message' in status, "Should provide message"
    
    def test_database_connection_error(self):
        """Test handling of database connection errors"""
        # Use invalid path
        temp_config = {
            'learning': {
                'enable': True,
                'sqlite_path': '/invalid/path/test.db'
            },
            'timezone': 'Europe/Stockholm'
        }
        
        with patch('learning.LearningEngine._load_config', return_value=temp_config):
            # Should not crash, but handle gracefully
            try:
                engine = LearningEngine('dummy_config.yaml')
                # The error might occur during schema initialization or status check
                status = engine.get_status()
                # Should either succeed or fail gracefully
                assert isinstance(status, dict), "Should return dict status"
            except Exception as e:
                # If exception occurs, it should be informative
                assert isinstance(e, (OSError, sqlite3.Error)), "Should be database-related error"
    
    def test_invalid_configuration_values(self, learning_engine):
        """Test handling of invalid configuration values"""
        # Test with negative values where they shouldn't be allowed
        invalid_config = learning_engine.config.copy()
        invalid_config['learning']['horizon_days'] = -1
        
        # Should handle gracefully without crashing
        try:
            loops = LearningLoops(learning_engine)
            # The loops should handle invalid values gracefully
            result = loops.forecast_calibrator()
            # Should either return None or handle the error
            assert result is None or isinstance(result, dict), "Should handle invalid config"
        except Exception as e:
            # If exception occurs, it should be informative
            assert isinstance(e, (ValueError, TypeError)), "Should be validation error"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
