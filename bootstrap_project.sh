#!/usr/bin/env bash
set -e

# --- Configurable Variables ---
PY_VERSION="3.11.9"                   # Python version for the project
VENV_NAME="reportsapp-3.11"           # Virtualenv name
PROJECT_DIR="$HOME/Desktop/ReportsFunctionApp"   # Path to your project
REQ_FILE="requirements.txt"           # Requirements file name

# --- Ensure project folder exists ---
mkdir -p "$PROJECT_DIR"

cd "$PROJECT_DIR"

echo ">>> Installing Python $PY_VERSION with pyenv (if not installed)..."
pyenv install -s "$PY_VERSION"

echo ">>> Creating virtualenv $VENV_NAME (if not exists)..."
if ! pyenv versions --bare | grep -q "^$VENV_NAME$"; then
  pyenv virtualenv "$PY_VERSION" "$VENV_NAME"
fi

echo ">>> Setting local Python version to $VENV_NAME..."
pyenv local "$VENV_NAME"

echo ">>> Upgrading pip..."
pip install --upgrade pip

if [[ -f "$REQ_FILE" ]]; then
  echo ">>> Installing dependencies from $REQ_FILE..."
  pip install -r "$REQ_FILE"
else
  echo ">>> No $REQ_FILE found, installing common packages..."
  pip install azure-functions psycopg2-binary pandas python-dotenv slack_sdk openpyxl
fi

echo ">>> Setup complete!"
echo "Project directory: $PROJECT_DIR"
echo "Python version: $(python --version)"
echo "Virtualenv: $VENV_NAME"
