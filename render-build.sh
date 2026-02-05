#!/usr/bin/env bash
# exit on error
set -o errexit

# Install Python requirements
pip install -r requirements.txt

# Install only the Chromium browser
# We REMOVE the 'install-deps' line because it requires root/sudo
playwright install chromium