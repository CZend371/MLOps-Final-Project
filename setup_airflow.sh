#!/usr/bin/env bash
set -euo pipefail

# -------------------------------------------------------
# MLOps Final Project — Airflow Setup Script
# Configures a project-isolated Airflow environment using
# SQLite and a local venv. Nothing is written to your
# shell profile (~/.bashrc, ~/.zshrc, etc.).
# -------------------------------------------------------

if [[ -n "${BASH_SOURCE[0]}" ]]; then
  PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
  PROJECT_ROOT="$(pwd)"
fi

VENV_DIR="$PROJECT_ROOT/venv"
AIRFLOW_HOME_DIR="$PROJECT_ROOT/airflow_home"

export AIRFLOW_HOME="$AIRFLOW_HOME_DIR"
export AIRFLOW__CORE__DAGS_FOLDER="$PROJECT_ROOT/dags"
export AIRFLOW__CORE__PLUGINS_FOLDER="$PROJECT_ROOT/plugins"
export AIRFLOW__LOGGING__BASE_LOG_FOLDER="$AIRFLOW_HOME/logs"
export AIRFLOW__DATABASE__SQL_ALCHEMY_CONN="sqlite:///$AIRFLOW_HOME/airflow.db"
export AIRFLOW__CORE__LOAD_EXAMPLES="False"

# AWS env vars — fill these in or export them before sourcing this script
export S3_BUCKET_NAME="${S3_BUCKET_NAME:-<PLACEHOLDER_S3_BUCKET_NAME>}"
export SQS_QUEUE_URL="${SQS_QUEUE_URL:-<PLACEHOLDER_SQS_QUEUE_URL>}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

echo "PROJECT_ROOT  = $PROJECT_ROOT"
echo "AIRFLOW_HOME  = $AIRFLOW_HOME"
echo "S3_BUCKET_NAME= $S3_BUCKET_NAME"
echo "SQS_QUEUE_URL = $SQS_QUEUE_URL"

# Create runtime directories
mkdir -p "$AIRFLOW_HOME"
mkdir -p "$PROJECT_ROOT/dags"
mkdir -p "$PROJECT_ROOT/plugins"
mkdir -p "$PROJECT_ROOT/models"
mkdir -p "$PROJECT_ROOT/data"
mkdir -p "$AIRFLOW_HOME/logs"

# Activate local virtual environment if it exists
if [[ -d "$VENV_DIR" ]]; then
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
  echo "Activated virtual environment: $VENV_DIR"
else
  echo "Warning: no virtual environment found at $VENV_DIR"
  echo "Create one with: python3 -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
fi

# Initialize or migrate Airflow metadata DB
airflow db init

echo
echo "Airflow environment is ready."
echo
echo "To use this environment in the current shell:"
echo "  source ./setup_airflow.sh"
echo
echo "Create an admin user (first time only):"
echo "  airflow users create \\"
echo "    --username admin \\"
echo "    --firstname Admin \\"
echo "    --lastname User \\"
echo "    --role Admin \\"
echo "    --email admin@example.com \\"
echo "    --password admin"
echo
echo "Then start Airflow (two separate terminals):"
echo "  airflow webserver --port 8080"
echo "  airflow scheduler"
