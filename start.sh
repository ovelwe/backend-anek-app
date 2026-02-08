#!/bin/bash
set -e
python -c "
from app import app, db
with app.app_context():
    db.create_all()
"
exec gunicorn --bind 0.0.0.0:${PORT:-8080} app:app
