FROM nginx:1.31.2-alpine

COPY landing/nginx.conf /etc/nginx/conf.d/default.conf
COPY landing/entrypoint.sh /docker-entrypoint-landing.sh
RUN chmod +x /docker-entrypoint-landing.sh

COPY landing/assets/ /usr/share/nginx/html/assets/
COPY landing/*.html /usr/share/nginx/html/

ENTRYPOINT ["/docker-entrypoint-landing.sh"]
CMD ["nginx", "-g", "daemon off;"]
