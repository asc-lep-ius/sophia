ARG CADDY_VERSION=2.11.3
ARG XCADDY_VERSION=v0.4.5
ARG RATELIMIT_VERSION=16aecbbcb8ca07dc1c671e263379606ff9493c55

FROM caddy:${CADDY_VERSION}-builder AS builder
ARG CADDY_VERSION
ARG XCADDY_VERSION
ARG RATELIMIT_VERSION
RUN go install github.com/caddyserver/xcaddy/cmd/xcaddy@${XCADDY_VERSION} && \
  caddy_version="${CADDY_VERSION#v}" && \
  /go/bin/xcaddy build "v${caddy_version}" \
      --output /usr/bin/caddy \
      --with github.com/mholt/caddy-ratelimit@${RATELIMIT_VERSION}

FROM caddy:${CADDY_VERSION}
COPY --from=builder /usr/bin/caddy /usr/bin/caddy
COPY Caddyfile /etc/caddy/Caddyfile
RUN /usr/bin/caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
