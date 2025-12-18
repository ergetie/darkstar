"""
Darkstar Native Executor Package

This package provides the native Python executor for Darkstar,
replacing the n8n Helios Executor workflow with a self-contained,
MariaDB-free implementation.

Modules:
    engine: Main executor loop and state machine
    override: Real-time override detection logic
    controller: Action decision-making from slot plans
    actions: Home Assistant action dispatcher
    history: Execution logging and history management
"""

from .engine import ExecutorEngine
from .config import ExecutorConfig, load_executor_config

__all__ = ["ExecutorEngine", "ExecutorConfig", "load_executor_config"]
