# Build context is the repository root: docker build -f renderer/Dockerfile .
FROM node:22-bookworm-slim AS build
WORKDIR /app/renderer
COPY renderer/package.json renderer/package-lock.json ./
RUN npm ci
COPY renderer/ ./
COPY schemas/ /app/schemas/
COPY data/fake/sample_a/match_info.json data/fake/sample_a/tracking.jsonl /app/data/fake/sample_a/
RUN npm run build

FROM node:22-bookworm-slim AS runtime
ENV NODE_ENV=production PORT=8080 HOST=0.0.0.0
WORKDIR /app
COPY --from=build --chown=node:node /app/renderer/dist ./dist
COPY --from=build --chown=node:node /app/renderer/scripts/serve.mjs ./scripts/serve.mjs
USER node
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD node -e "fetch('http://127.0.0.1:'+process.env.PORT+'/healthz').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "scripts/serve.mjs"]
