#!/usr/bin/env bash
# Run locally, reachable only from this computer.
cd "$(dirname "$0")"
exec .venv/bin/streamlit run app.py --server.address localhost --server.port 8501
