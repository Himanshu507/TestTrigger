#!/bin/sh
# Publish the local API base URL to the page at container start.
#
# This is the only configuration the browser receives. An API key must never be
# written here: anything in this file is served to the browser verbatim.
set -eu

API_BASE="${API_BASE_URL:-http://localhost:8000}"
TARGET=/usr/share/nginx/html/config.js

printf 'window.TEST_TRIGGER_API_BASE = "%s";\n' "$API_BASE" > "$TARGET"
echo "Frontend configured to call ${API_BASE}"
