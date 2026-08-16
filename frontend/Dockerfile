FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
# ponytail: build ARGs, not runtime env -- Next.js inlines NEXT_PUBLIC_* into the
# client bundle at `next build`, so these must be known at image-build time (e.g.
# `docker build --build-arg NEXT_PUBLIC_API_BASE_URL=https://<backend-host>/api/v1`),
# not set later as a container's runtime env var.
ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_SCANNER_SERVER_ORIGIN
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_SCANNER_SERVER_ORIGIN=${NEXT_PUBLIC_SCANNER_SERVER_ORIGIN}
RUN npm run build

FROM node:22-slim AS run
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app/public ./public
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

EXPOSE 3000
CMD ["node", "server.js"]
