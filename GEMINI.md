# GEMINI.md - Darkstar Energy Manager

This document provides a comprehensive overview of the Darkstar Energy Manager project, intended to be used as a context for AI-powered development assistance.

## Project Overview

Darkstar Energy Manager is a sophisticated, Python-based Model Predictive Control (MPC) system designed for optimizing residential energy usage. It focuses on intelligent battery scheduling and water heating to minimize energy costs.

The system is transitioning to a **Kepler (MILP)** centric architecture:

1.  **Data Ingestion**: Fetches electricity prices from the Nordpool API, PV generation forecasts from Open-Meteo, and real-time sensor data from Home Assistant.
2.  **Aurora Forecasting**: Uses LightGBM models (`ml/`) to predict load and PV generation with uncertainty.
3.  **Strategy Engine**: An RL/Policy layer (`backend/strategy/`) that assesses risk and sets parameters (`θ`) for the planner.
4.  **Kepler Planner**: The core MILP solver (`planner.py` / `ml/benchmark/milp_solver.py`) that generates the optimal schedule based on forecasts and strategy parameters.
5.  **Web UI**: A Flask + React web application provides a dashboard for visualizing the energy schedule and system status.

### Key Technologies

*   **Backend**: Python
*   **Core Logic**: Pandas, PuLP (MILP Solver)
*   **Web Framework**: Flask + React (Vite)
*   **Configuration**: YAML (`config.yaml`)
*   **Data Sources**: Nordpool API, Open-Meteo API, Home Assistant.

### Core Files

*   `planner.py`: The main planning logic (transitioning to MILP).
*   `ml/benchmark/milp_solver.py`: The Kepler MILP solver prototype.
*   `backend/strategy/engine.py`: The Strategy Engine.
*   `inputs.py`: Handles all external data fetching.
*   `config.yaml`: The central configuration file.
*   `AGENTS.md`: Development guidelines and protocols.

## Building and Running

### Prerequisites

*   Python 3.12.0
*   A Python virtual environment.

### Installation

1.  **Set up the virtual environment**:
    ```bash
    python -m venv venv
    source venv/bin/activate
    ```

2.  **Install dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

### Running the Application

*   **Run the Planner (generates `schedule.json`)**:
    ```bash
    python planner.py
    ```

*   **Run the Web UI**:
    ```bash
    FLASK_APP=webapp flask run --host 0.0.0.0 --port 8000
    ```

*   **Run Tests**:
    ```bash
    PYTHONPATH=. python -m pytest -q
    ```

## Development Conventions

*   **Code Formatting**: The project uses `black` for code formatting. The configuration is in `pyproject.toml`.
*   **Linting**: `flake8` is used for linting.
*   **Pre-commit Hooks**: The project is set up to use `pre-commit` to automatically run `black` and `flake8` before each commit. To install the hooks, run:
    ```bash
    pre-commit install
    ```
*   **Configuration**: All operational parameters are managed through `config.yaml`. Avoid hardcoding values; instead, add them to the configuration file.
*   **Dependencies**: Add new Python dependencies to `requirements.txt`.
