# The app itself: the built SPA, and /api passed to FastAPI.
#
# Included by both listeners in default.conf, which differ only in how they
# say who the visitor is ($gg_forwarded_for, $gg_forwarded_proto) and in what
# the plain one serves once HTTPS is on. Not a *.conf file, so nginx does not
# load it on its own.

root /usr/share/nginx/html;
index index.html;

gzip on;
gzip_types text/css application/javascript application/json image/svg+xml;
gzip_min_length 1024;

client_max_body_size 25M;   # CSV/Excel imports

# For the container's health check: answered by nginx itself, so "web is up"
# never depends on the API, and never on HTTPS (the plain port redirects "/").
location = /healthz {
    access_log off;
    return 200 "ok\n";
}

location /api/ {
    # The upstream is a VARIABLE, resolved through Docker's embedded DNS at
    # request time — not a literal hostname.
    #
    # With a literal `proxy_pass http://api:8000`, nginx resolves the name
    # at startup and exits with "host not found in upstream" if the api
    # container isn't up yet. That makes nginx depend on boot order, and it
    # dies if the API is ever removed. Deferring resolution means nginx
    # starts regardless and simply returns 502 until the API answers.
    resolver 127.0.0.11 valid=10s;
    set $upstream api;
    proxy_pass http://$upstream:8000$request_uri;

    proxy_http_version 1.1;
    proxy_set_header Upgrade           $http_upgrade;
    proxy_set_header Connection        $connection_upgrade;
    proxy_set_header Host              $host;
    proxy_set_header X-Real-IP         $remote_addr;
    # Who the visitor is, as the listener knows it — the API takes the last
    # entry (TRUSTED_PROXY_HOPS=1) for sign-in limits, sessions and the
    # activity log (P5-1). See the two server blocks in default.conf.
    proxy_set_header X-Forwarded-For   $gg_forwarded_for;
    # https when the visitor came through Caddy: session cookies are made
    # Secure from it.
    proxy_set_header X-Forwarded-Proto $gg_forwarded_proto;

    # Imports and connector syncs can legitimately run long.
    proxy_read_timeout 120s;
}

# Filenames are content-hashed, so these can never go stale.
location /assets/ {
    expires 1y;
    add_header Cache-Control "public, immutable" always;

    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
}

location / {
    # SPA fallback: /goals/12 has no file on disk, so serve index.html and
    # let React Router handle it. This is what makes a hard refresh or a
    # pasted deep link work.
    try_files $uri $uri/ /index.html;

    # index.html must never be cached — it points at hashed asset names, so
    # a stale copy references files that no longer exist.
    add_header Cache-Control "no-cache" always;

    # Repeated in every location block that sets any header. nginx's
    # add_header does NOT merge across levels: a block with its own
    # add_header silently discards all inherited ones. Declaring these once
    # at server level would drop them exactly here, on the HTML document,
    # leaving the app open to clickjacking.
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
}
