#!/usr/bin/env bash
# Serve VITRA from this computer at a public HTTPS address through a free Cloudflare quick tunnel.
# Sign-in is always on. The site stays up only while this script runs and the computer is awake.
#
#   deploy/serve_public.sh            first run asks for a sign-in password
#   deploy/serve_public.sh --reset    choose a new username and password
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/deploy/.env.public"   # git-ignored, readable only by you
PORT="${PORT:-7860}"

command -v cloudflared >/dev/null || { echo "cloudflared is missing. Install it with: brew install cloudflared"; exit 1; }
[ -x "$ROOT/backend/.venv/bin/uvicorn" ] || { echo "Set up the backend first (see Quick start in README.md)."; exit 1; }
[ "${1:-}" = "--reset" ] && rm -f "$ENV_FILE"

if [ ! -f "$ENV_FILE" ]; then
  read -rp "Sign-in username [admin]: " username
  username="${username:-admin}"
  while :; do
    read -rsp "Choose a sign-in password (at least 12 characters): " password; echo
    read -rsp "Repeat the password: " again; echo
    [ "$password" = "$again" ] && [ "${#password}" -ge 12 ] && break
    echo "Passwords must match and be at least 12 characters."
  done
  ( umask 077; printf 'AUTH_USERNAME=%q\nAUTH_PASSWORD=%q\nSESSION_SECRET=%q\n' \
      "$username" "$password" "$(openssl rand -hex 32)" > "$ENV_FILE" )
  unset password again
  echo "Saved to deploy/.env.public"
fi

echo "Building the web app..."
(cd "$ROOT/frontend" && npm run build >/dev/null)

set -a; . "$ENV_FILE"; set +a
export FRONTEND_DIST="$ROOT/frontend/dist" REQUIRE_AUTH=true COOKIE_SECURE=true CORS_ORIGINS=""

cd "$ROOT/backend"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --proxy-headers --forwarded-allow-ips=127.0.0.1 &
server=$!
trap 'kill "$server" 2>/dev/null; wait "$server" 2>/dev/null' EXIT INT TERM

for _ in $(seq 1 60); do
  curl -fs "http://127.0.0.1:$PORT/api/health" >/dev/null && break
  kill -0 "$server" 2>/dev/null || { echo "The VITRA server stopped. See the error above."; exit 1; }
  sleep 1
done

echo
echo "VITRA is running. Your public link is the https://...trycloudflare.com address printed below."
echo "Sign in as '$AUTH_USERNAME'. Press Ctrl-C to take the site offline."
echo
# caffeinate keeps the Mac from sleeping while the site is online.
caffeinate -i cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$PORT"
