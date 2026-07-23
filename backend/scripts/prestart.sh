#! /usr/bin/env bash

set -e
set -x

# Let the DB start
python app/backend_pre_start.py

# Let object storage start and ensure the artifacts bucket exists
python app/storage_pre_start.py

# Run migrations
alembic upgrade head

# Create initial data in DB
python app/initial_data.py
