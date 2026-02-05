#!/usr/bin/env bash
# exit on error
set -o errexit

pip install -r requirements.txt

# Install Playwright browsers and system dependencies
playwright install chromium
playwright install-deps chromium