#!/bin/bash
set -e
python init_db.py
exec gunicorn --bind 0.0.0.0:${PORT:-8080} app:app
