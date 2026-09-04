# Stage: dev — Vite dev server with HMR for docker compose watch
# Pinned by digest, not just by tag: `oven/bun` republishes :1 on every release,
# so the tag alone does not make the build reproducible.
FROM oven/bun:1@sha256:9e123d5fc069e29d519fd4c981afb61b8542ac80274771961136db1e4538d53e AS dev-stage

WORKDIR /app

COPY package.json bun.lock /app/
COPY frontend/package.json /app/frontend/

WORKDIR /app/frontend

RUN bun install

COPY ./frontend /app/frontend

EXPOSE 5173

CMD ["bun", "run", "dev", "--host", "0.0.0.0"]


# Stage 0, "build-stage", based on Bun, to build and compile the frontend
FROM oven/bun:1@sha256:9e123d5fc069e29d519fd4c981afb61b8542ac80274771961136db1e4538d53e AS build-stage

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
# The version is not here: vite.config.ts bakes it in from frontend/package.json,
# which is already in the build context. Only the things that differ per
# deployment of the same source need passing in.
ARG VITE_APP_ENVIRONMENT
ARG VITE_APP_COMMIT

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
FROM nginxinc/nginx-unprivileged:1.31.5-alpine@sha256:aa8c9087d36d93e9d650c5365f883b421e8214aedbad24ade52b844c583358f1

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
