#!/bin/sh
# GoalGetter first-time setup (Mac / Linux).
#
# Creates .env from .env.example with fresh random secrets, and optionally
# switches HTTPS on for a name:
#
#   sh setup.sh                          # plain HTTP on this computer
#   sh setup.sh --https goals.internal   # HTTPS, with GoalGetter's own certificate
#
# Then:  docker compose up -d
#
# Never touches an existing .env: a new database password would lock you out
# of the database it already made, and a new encryption key would make every
# stored credential unreadable. Edit .env by hand instead.
set -e
cd "$(dirname "$0")"

HOST=""
while [ $# -gt 0 ]; do
  case "$1" in
    --https)
      # Said, not a silent exit under `set -e` (P5-4).
      if [ $# -lt 2 ] || [ -z "$2" ]; then
        echo "--https needs a name after it, e.g.  sh setup.sh --https goals.internal"
        exit 2
      fi
      HOST="$2"; shift ;;
    -h|--help) sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (try --help)"; exit 2 ;;
  esac
  shift
done

if [ -n "$HOST" ]; then
  # A bare name or address: "https://goals.internal" or a space would be
  # written into HTTPS_HOST as it is, and nothing would work (P5-4).
  case "$HOST" in
    *://*) echo "Give just the name, without https:// — e.g. goals.internal"; exit 2 ;;
    # P6-4: the port has its own setting.
    *:*) echo "Leave the port out: give just the name, then set HTTPS_PORT in .env (e.g. HTTPS_PORT=8443)"; exit 2 ;;
  esac
  if ! printf '%s' "$HOST" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?$'; then
    echo "\"$HOST\" is not a name or address. Use letters, digits, dots and dashes, e.g. goals.internal"
    exit 2
  fi
fi

if [ -f .env ]; then
  echo ".env already exists, so nothing was changed. Edit it by hand —"
  echo "see documentation/20-hosting.md."
  exit 1
fi

secret() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  else
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n'
  fi
}

sed -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$(secret)|" \
    -e "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$(secret)|" \
    .env.example > .env

if [ -n "$HOST" ]; then
  sed -e "s|^HTTPS_HOST=.*|HTTPS_HOST=$HOST|" .env > .env.tmp && mv .env.tmp .env
fi

if [ -d volumes/postgres/18 ]; then
  echo "Warning: volumes/postgres already holds a database, made with an older"
  echo "password. Put that password in .env as POSTGRES_PASSWORD, or the app"
  echo "cannot connect to it."
fi

echo "Created .env with new secrets."
echo
echo "Next:"
echo "  docker compose up -d"
if [ -n "$HOST" ]; then
  echo "  then open https://$HOST  (and see documentation/20-hosting.md to trust it)"
else
  echo "  then open http://localhost:8080"
fi
