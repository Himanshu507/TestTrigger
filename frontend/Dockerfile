# Frontend: static chat client served by nginx.
#
# The page is buildless, so there is no bundler step and no build argument that
# could capture a secret. The container receives one value — the local API base
# URL — and never an API key.
FROM nginx:1.29-alpine

COPY index.html styles.css app.js /usr/share/nginx/html/
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY entrypoint.sh /docker-entrypoint.d/40-api-base.sh
RUN chmod +x /docker-entrypoint.d/40-api-base.sh

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD wget --spider -q http://127.0.0.1/ || exit 1
