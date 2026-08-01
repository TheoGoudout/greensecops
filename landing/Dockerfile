# nginx-unprivileged rather than the stock nginx image: it is the same upstream
# build with the cache, run and log directories already owned by uid 101, so the
# server runs unprivileged without a chown layer of our own. An unprivileged
# process cannot bind a port below 1024, which is why landing/nginx.conf listens
# on 8080 and the deployment's container port is 8080 rather than 80.
FROM nginxinc/nginx-unprivileged:1.31.3-alpine@sha256:59ccf0943b0b8e8d9e6ea9039a39555730f544701a655c596f7df7d096c593f5

LABEL org.opencontainers.image.source="https://github.com/TheoGoudout/greensecops"
LABEL org.opencontainers.image.licenses="MIT"

COPY landing/nginx.conf /etc/nginx/conf.d/default.conf
# --chmod on the COPY rather than a `RUN chmod`: the base image already runs as
# uid 101, which cannot chmod a root-owned file.
COPY --chmod=0755 landing/entrypoint.sh /docker-entrypoint-landing.sh

# --chown so the entrypoint's envsubst pass can rewrite these pages in place as
# uid 101. The docroot directory itself stays root-owned, which is why the
# entrypoint writes its temporary file outside the docroot.
COPY --chown=101:101 landing/assets/ /usr/share/nginx/html/assets/
COPY --chown=101:101 landing/*.html /usr/share/nginx/html/

# wget, not curl: the alpine image ships busybox wget and no curl at all.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O /dev/null http://localhost:8080/ || exit 1

# Inherited from the base image, but stated here so the shipped uid is visible
# in this file and survives a future base-image change.
USER 101

ENTRYPOINT ["/docker-entrypoint-landing.sh"]
CMD ["nginx", "-g", "daemon off;"]
