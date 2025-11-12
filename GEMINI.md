# GEMINI.md - Darkstar Energy Manager

This document provides a comprehensive overview of the Darkstar Energy Manager project, intended to be used as a context for AI-powered development assistance.

## Project Overview

Darkstar Energy Manager is a sophisticated, Python-based Model Predictive Control (MPC) system designed for optimizing residential energy usage. It focuses on intelligent battery scheduling and water heating to minimize energy costs.

The system operates in a multi-pass process to generate an optimal energy plan:

1.  **Data Ingestion**: Fetches electricity prices from the Nordpool API, PV generation forecasts from Open-Meteo, and real-time sensor data (like battery state-of-charge) from Home Assistant.
2.  **MPC Planning**: The core logic, implemented in `planner.py`, runs a series of passes to build an optimized schedule. This includes identifying cheap charging windows, scheduling water heating, and simulating battery depletion.
3.  **Cascading Responsibility**: A key feature is the "cascading responsibility" logic, where cheap charging windows are allocated the task of charging for future, more expensive periods.
4.  **Web UI**: A Flask-based web application (`webapp.py`) provides a dashboard for visualizing the energy schedule, system status, and manual control over the planner.

### Key Technologies

*   **Backend**: Python
*   **Core Logic**: Pandas for data manipulation and time-series analysis.
*   **Web Framework**: Flask
*   **Configuration**: YAML (`config.yaml`)
*   **Frontend**: JavaScript, with `vis-timeline` for charting.
*   **Data Sources**: Nordpool API, Open-Meteo API, Home Assistant.

### Core Files

*   `planner.py`: The main MPC planning and scheduling logic.
*   `inputs.py`: Handles all external data fetching.
*   `webapp.py`: The Flask web application and API.
*   `config.yaml`: The central configuration file for all system parameters.
*   `requirements.txt`: Lists all Python dependencies.

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
