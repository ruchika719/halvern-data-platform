#!/usr/bin/env bash
# Prepare a local development environment: Java 17 for Spark 3.5, and a
# Python 3.12 virtualenv with the dev requirements. Safe to run repeatedly.
set -euo pipefail

cd "$(dirname "$0")/.."

JAVA17_HOME=/usr/lib/jvm/java-17-openjdk-amd64

if [ ! -x "$JAVA17_HOME/bin/java" ]; then
  echo "Installing OpenJDK 17..."
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq openjdk-17-jdk-headless
fi

if [ ! -x .venv/bin/python ]; then
  python3.12 -m venv .venv
fi
.venv/bin/pip install -q -r requirements-dev.txt

echo "Done. Before running tests:"
echo "  export JAVA_HOME=$JAVA17_HOME"
echo "  source .venv/bin/activate"
