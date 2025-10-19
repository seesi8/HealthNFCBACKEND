#!/usr/bin/env bash
set -euo pipefail

# If the FIREBASE_ADMIN_JSON secret is provided, write it to firebase-admin.json
if [ -n "${FIREBASE_ADMIN_JSON-}" ]; then
  echo "Writing firebase-admin.json from FIREBASE_ADMIN_JSON environment variable"
  printf "%s" "$FIREBASE_ADMIN_JSON" > /app/firebase-admin.json
  chmod 600 /app/firebase-admin.json
fi

# If GOOGLE_APPLICATION_CREDENTIALS is set, ensure it points to our file
if [ -z "${GOOGLE_APPLICATION_CREDENTIALS-}" ]; then
  export GOOGLE_APPLICATION_CREDENTIALS=/app/firebase-admin.json
fi

exec "$@"
