FROM caddy:2-alpine

RUN apk add --no-cache nss-tools

COPY Caddyfile /etc/caddy/Caddyfile

# Expose non-privileged ports for rootless operation
EXPOSE 8080
EXPOSE 8443
