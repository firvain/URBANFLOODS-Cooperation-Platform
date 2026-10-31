#!/usr/bin/env bash
# Host nginx: refuse requests for hostnames this server does not host.
#
# Without it, a request for an unknown name over HTTPS is answered by the first HTTPS site nginx
# loads (the Cooperation Platform) and over HTTP by Ubuntu's stock "Welcome to nginx" page. This
# replaces the stock `default` site with a catch-all that refuses the TLS handshake on 443 (no
# certificate needed, `ssl_reject_handshake`) and closes HTTP connections without a reply (444).
# Sites that match by name (knowbase.urbanfloods.app, cooperation.urbanfloods.app) and certbot
# renewals are not affected.
#
# Run on the server, as the owner:
#   sudo ~/URBANFLOODS-Cooperation-Platform/docker/nginx-catch-all.sh          # install
#   sudo ~/URBANFLOODS-Cooperation-Platform/docker/nginx-catch-all.sh --undo   # restore default
#
# Safe to run twice. If `nginx -t` fails, the previous state is restored and nothing is reloaded.
set -euo pipefail

AVAILABLE=/etc/nginx/sites-available
ENABLED=/etc/nginx/sites-enabled
CATCH_ALL=catch-all
LIVE_SITES=(knowbase.urbanfloods.app cooperation.urbanfloods.app)

log() { echo "[nginx-catch-all] $*"; }
fail() {
    echo "[nginx-catch-all] ERROR: $*" >&2
    exit 1
}

[ "$(id -u)" -eq 0 ] || fail "run with sudo"
command -v nginx >/dev/null || fail "nginx not found"

# Each live site must still answer through this nginx (checked against 127.0.0.1 with its name).
check_live_sites() {
    local ok=0 site code
    for site in "${LIVE_SITES[@]}"; do
        code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' --resolve "$site:443:127.0.0.1" "https://$site/" || true)
        if [ "$code" = "200" ]; then
            log "  $site -> $code"
        else
            log "  $site -> $code (expected 200)"
            ok=1
        fi
    done
    return $ok
}

test_and_reload() {
    if nginx -t 2>/dev/null; then
        systemctl reload nginx
        log "nginx reloaded"
        return 0
    fi
    nginx -t || true
    return 1
}

if [ "${1:-}" = "--undo" ]; then
    log "Restoring the stock default site"
    [ -e "$AVAILABLE/default" ] || fail "$AVAILABLE/default is missing; nothing to restore"
    rm -f "$ENABLED/$CATCH_ALL"
    ln -sfn "$AVAILABLE/default" "$ENABLED/default"
    test_and_reload || fail "nginx -t failed after undo; check the output above"
    check_live_sites || log "warning: a live site did not answer 200"
    log "Done (catch-all removed, default site enabled)."
    exit 0
fi

had_default=0
[ -L "$ENABLED/default" ] || [ -e "$ENABLED/default" ] && had_default=1

log "Writing $AVAILABLE/$CATCH_ALL"
cat >"$AVAILABLE/$CATCH_ALL" <<'EOF'
# Requests for hostnames this server does not host: refuse them.
# Installed by URBANFLOODS-Cooperation-Platform/docker/nginx-catch-all.sh (undo: --undo).
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name _;
    ssl_reject_handshake on;   # HTTPS: refuse the TLS handshake (no certificate needed)
    return 444;                # HTTP: close the connection without a reply
}
EOF

log "Enabling the catch-all, disabling the stock default site"
rm -f "$ENABLED/default"
ln -sfn "$AVAILABLE/$CATCH_ALL" "$ENABLED/$CATCH_ALL"

if ! test_and_reload; then
    log "nginx -t failed: restoring the previous state"
    rm -f "$ENABLED/$CATCH_ALL"
    [ "$had_default" -eq 1 ] && ln -sfn "$AVAILABLE/default" "$ENABLED/default"
    nginx -t >/dev/null 2>&1 && log "previous configuration restored (not reloaded: it was never changed live)"
    exit 1
fi

log "Checking the live sites"
if ! check_live_sites; then
    log "A live site did not answer 200: undoing"
    rm -f "$ENABLED/$CATCH_ALL"
    [ "$had_default" -eq 1 ] && ln -sfn "$AVAILABLE/default" "$ENABLED/default"
    test_and_reload || true
    fail "catch-all removed again; nothing changed"
fi

log "Checking an unknown hostname (should be refused)"
code=$(curl -sk -o /dev/null -m 5 -w '%{http_code}' --resolve "unknown.invalid:443:127.0.0.1" https://unknown.invalid/ || true)
log "  https://unknown.invalid -> ${code:-000} (000 = refused, as intended)"

log "Done. Undo with: sudo $0 --undo"
