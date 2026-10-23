#!/bin/sh
set -eu

for secret in "$HELLO_MIGRATOR_PASSWORD" "$HELLO_APP_PASSWORD" "$HELLO_WORKER_PASSWORD"; do
  if [ "${#secret}" -lt 32 ]; then
    echo "Database service passwords must be at least 32 URL-safe characters" >&2
    exit 1
  fi
  case "$secret" in
    *[!A-Za-z0-9_-]*) echo "Database passwords must use letters, digits, underscore, or hyphen" >&2; exit 1 ;;
  esac
done

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE hello_migrator LOGIN PASSWORD '$HELLO_MIGRATOR_PASSWORD';
CREATE ROLE hello_app LOGIN PASSWORD '$HELLO_APP_PASSWORD';
CREATE ROLE hello_worker LOGIN PASSWORD '$HELLO_WORKER_PASSWORD';
GRANT CONNECT ON DATABASE $POSTGRES_DB TO hello_migrator, hello_app, hello_worker;
GRANT USAGE, CREATE ON SCHEMA public TO hello_migrator;
SQL
