# Stage: dev — Vite dev server with HMR for docker compose watch
# Pinned by digest, not just by tag: `oven/bun` republishes :1 on every release,
# so the tag alone does not make the build reproducible.
FROM oven/bun:1@sha256:e10577f0db68676a7024391c6e5cb4b879ebd17188ab750cf10024a6d700e5c4 AS dev-stage

WORKDIR /app

COPY package.json bun.lock /app/
COPY frontend/package.json /app/frontend/

WORKDIR /app/frontend

RUN bun install

COPY ./frontend /app/frontend

EXPOSE 5173

CMD ["bun", "run", "dev", "--host", "0.0.0.0"]


# Stage 0, "build-stage", based on Bun, to build and compile the frontend
FROM oven/bun:1@sha256:e10577f0db68676a7024391c6e5cb4b879ebd17188ab750cf10024a6d700e5c4 AS build-stage

WORKDIR /app

COPY package.json bun.lock /app/

COPY frontend/package.json /app/frontend/

WORKDIR /app/frontend

RUN bun install

COPY ./frontend /app/frontend
ARG VITE_API_URL
ARG VITE_GREENSECOPS_PUBLIC_URL
ARG VITE_GITHUB_OAUTH_CLIENT_ID
ARG VITE_GITHUB_APP_NAME

RUN bun run build


# Stage 1, based on Nginx, to have only the compiled app, ready for production
# with Nginx.
#
# nginx-unprivileged rather than the stock nginx image: it is the same upstream
# build with the cache, run and log directories already owned by uid 101, so the
# server runs unprivileged without a chown layer of our own. An unprivileged
# process cannot bind a port below 1024, which is why frontend/nginx.conf listens
# on 8080 and the deployment's container port is 8080 rather than 80.
#
# The alpine variant also drops the `apt-get install curl` layer this stage used
# to carry purely to satisfy the health check — the nginx alpine images install
# curl themselves.
FROM nginxinc/nginx-unprivileged:1.31.3-alpine@sha256:59ccf0943b0b8e8d9e6ea9039a39555730f544701a655c596f7df7d096c593f5

LABEL org.opencontainers.image.source="https://github.com/TheoGoudout/greensecops"
LABEL org.opencontainers.image.licenses="MIT"

COPY --from=build-stage /app/frontend/dist/ /usr/share/nginx/html

COPY ./frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY ./frontend/nginx-backend-not-found.conf /etc/nginx/extra-conf.d/backend-not-found.conf

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS -o /dev/null http://localhost:8080/ || exit 1

# Inherited from the base image, but stated here so the shipped uid is visible
# in this file and survives a future base-image change.
USER 101
