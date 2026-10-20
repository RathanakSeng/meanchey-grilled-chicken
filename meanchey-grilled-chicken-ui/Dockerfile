# Production image: builds the SPA, then serves it with nginx. nginx also terminates TLS
# (Cloudflare Origin Certificate, mounted at /etc/ssl/cloudflare) and proxies /api/* to the api
# service, so the Mini App, the API and the Telegram webhook share one origin.

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# Same-origin API by default; no build arg needed behind the bundled proxy.
ARG VITE_API_BASE_URL=/api/v1
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:1.27-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY deploy/cloudflare-real-ip.conf /etc/nginx/conf.d/cloudflare-real-ip.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80 443
HEALTHCHECK --interval=10s --timeout=3s --retries=5 \
  CMD wget -q --spider http://127.0.0.1/nginx-health || exit 1
