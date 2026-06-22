FROM node:22-slim AS build

WORKDIR /app/web

COPY web/package.json web/package-lock.json* ./
RUN npm ci

COPY web /app/web
ARG VITE_PLANORA_API_URL=/api
ENV VITE_PLANORA_API_URL=${VITE_PLANORA_API_URL}
RUN npm run build

FROM caddy:2.9-alpine

COPY deploy/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/web/dist /srv
