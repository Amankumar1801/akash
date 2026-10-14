# syntax=docker/dockerfile:1.7
# Static frontend behind nginx, which also proxies /v1 to the API (same origin: no CORS needed).
#   docker build -f infra/docker/web.Dockerfile -t akash-web .
FROM node:22-alpine AS build
ARG VITE_DEFAULT_MODE=live
ENV VITE_DEFAULT_MODE=$VITE_DEFAULT_MODE
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime
COPY infra/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
