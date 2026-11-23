# Bundle the existing Photon transport into the same Ash deployment.
FROM public.ecr.aws/docker/library/node:22-bookworm-slim AS photon-build
WORKDIR /photon
ENV NODE_OPTIONS=--max-old-space-size=384
COPY integrations/photon/package*.json ./
RUN npm ci
COPY integrations/photon/tsconfig.json integrations/photon/build.mjs ./
COPY integrations/photon/src ./src
RUN npm run build && npm prune --omit=dev
WORKDIR /qq
COPY integrations/qq/package*.json ./
RUN npm ci --omit=dev --ignore-scripts

WORKDIR /social
COPY integrations/social/package*.json ./
RUN npm ci --omit=dev --ignore-scripts

FROM public.ecr.aws/docker/library/python:3.12-slim-bookworm
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libstdc++6 ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=photon-build /usr/local/bin/node /usr/local/bin/node
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
COPY --from=photon-build /photon/dist ./integrations/photon/dist
COPY --from=photon-build /photon/node_modules ./integrations/photon/node_modules
COPY --from=photon-build /qq/node_modules ./integrations/qq/node_modules
COPY --from=photon-build /social/node_modules ./integrations/social/node_modules
ENV PORT=8000
CMD ["python", "main.py"]
