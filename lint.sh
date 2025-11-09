#!/usr/bin/env bash
source venv/bin/activate
echo "Running black..."
black .
echo "Running flake8..."
flake8 --jobs=1 .
