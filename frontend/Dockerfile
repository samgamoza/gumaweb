# GumaWeb portal (admin console + customer portal + claim flow)
FROM node:22-alpine AS deps
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

FROM node:22-alpine AS build
RUN corepack enable
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /app
RUN addgroup -S -g 10001 gumaweb && adduser -S -u 10001 -G gumaweb gumaweb
COPY --from=build --chown=gumaweb:gumaweb /app/.next/standalone ./
COPY --from=build --chown=gumaweb:gumaweb /app/.next/static ./.next/static
COPY --from=build --chown=gumaweb:gumaweb /app/public ./public
USER gumaweb
EXPOSE 3000
CMD ["node", "server.js"]
