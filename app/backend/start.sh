#!/usr/bin/env sh
set -e
python -m app.seed || true
exec uvicorn main:app --host 0.0.0.0 --port 8080
