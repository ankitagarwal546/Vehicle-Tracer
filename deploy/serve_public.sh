#!/usr/bin/env bash
# Serve VITRA from this computer at a public HTTPS address through a free tunnel:
# a Cloudflare quick tunnel when reachable, otherwise Pinggy over SSH (see TUNNEL below).
# Sign-in is always on. The site stays up only while this script runs and the computer is awake.
#
#   deploy/serve_public.sh            first run asks for a sign-in password
#   deploy/serve_public.sh --reset    choose a new username and password
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/deploy/.env.public"   # git-ignored, readable only by you
PORT="${PORT:-7860}"

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
echo "VITRA is running locally. Sign in as '$AUTH_USERNAME'. Press Ctrl-C to take the site offline."
echo

# caffeinate keeps the Mac from sleeping while the site is online.
# Order: Cloudflare quick tunnel, then Pinggy, then localhost.run. TUNNEL=cloudflare|pinggy|localhostrun forces one.
choice="${TUNNEL:-auto}"
if [ "$choice" = "auto" ]; then
  if command -v cloudflared >/dev/null && curl -s -o /dev/null --max-time 8 -X POST https://api.trycloudflare.com/tunnel; then
    choice=cloudflare
  else
    choice=pinggy
  fi
fi

case "$choice" in
  cloudflare)
    echo "Opening a Cloudflare tunnel. Your public link is the https://...trycloudflare.com address below."
    caffeinate -i cloudflared tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" ;;
  pinggy)
    echo "Opening a Pinggy tunnel. Your public link is the https://...pinggy... address below."
    echo "Free Pinggy links last 60 minutes, so the script reconnects and prints a NEW link each hour."
    # Pinggy's free tier accepts an empty password; answer its prompt automatically.
    askpass="$(mktemp -t vitra-askpass)"
    printf '#!/bin/sh\necho\n' > "$askpass"; chmod 700 "$askpass"
    trap 'rm -f "$askpass"; kill "$server" 2>/dev/null; wait "$server" 2>/dev/null' EXIT INT TERM
    while kill -0 "$server" 2>/dev/null; do
      SSH_ASKPASS="$askpass" SSH_ASKPASS_REQUIRE=force caffeinate -i ssh -T -o ServerAliveInterval=30 \
        -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new \
        -o PreferredAuthentications=password,keyboard-interactive \
        -p 443 -R "0:127.0.0.1:$PORT" a.pinggy.io || true
      echo "Tunnel closed. Reconnecting with a new link..."
      sleep 3
    done ;;
  localhostrun)
    echo "Opening a localhost.run tunnel (heavily throttled on the free plan)."
    caffeinate -i ssh -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -o StrictHostKeyChecking=accept-new \
      -R "80:127.0.0.1:$PORT" nokey@localhost.run ;;
  *) echo "Unknown TUNNEL value: $choice"; exit 1 ;;
esac
