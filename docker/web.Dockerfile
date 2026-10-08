# Build the SPA, then ship only the static output.
#
# The runtime image contains no Node and no node_modules — just nginx and a few
# hundred KB of files. Smaller, and far less to attack.

FROM node:24-alpine AS build
WORKDIR /build

# Dependencies first: editing source then doesn't invalidate this layer.
COPY web/package.json web/package-lock.json* ./
RUN npm ci

COPY web/ ./
RUN npm run build

FROM nginx:1.29-alpine
COPY --from=build /build/dist /usr/share/nginx/html
# The same config development mounts, baked in — so routing, cache headers and
# the /api proxy are identical in both. A second copy under docker/ is what this
# line used to point at, and it did not exist: the web image could not build at
# all, which only shows up on a host with no cached image.
COPY nginx/conf.d/default.conf nginx/conf.d/app.inc /etc/nginx/conf.d/
# Writes the HTTPS address for the plain port before nginx starts (P5-3).
COPY docker/web-https.sh /docker-entrypoint.d/40-goalgetter-https.sh
RUN chmod +x /docker-entrypoint.d/40-goalgetter-https.sh
EXPOSE 80 81
