# Node 24 (Alpine) — the current Active LTS line, and comfortably above the
# `node >=20.9.0` that Next.js 16 requires. Pinned to a major for the same
# reason the database is: `node:latest` would let this machine and a
# reviewer's machine resolve to different runtimes.
FROM node:24-alpine AS base

WORKDIR /app

# --- dependencies ------------------------------------------------------------
# Installed in their own layer, BEFORE application code is copied, so editing a
# component does not re-run the install. Docker invalidates a layer only when
# its inputs change, and the inputs here are the two manifest files.
FROM base AS deps

COPY package.json package-lock.json ./

# `npm ci`, not `npm install`. ci installs exactly the tree package-lock.json
# pins and fails outright if the lockfile and package.json disagree; install
# would quietly resolve newer versions and rewrite the lockfile, so two builds
# of the same commit could produce different dependency trees.
RUN npm ci

# --- development -------------------------------------------------------------
# The target docker-compose.yml builds. Source is overlaid by a bind mount at
# runtime (see docker-compose.yml), so what is copied here is only a sensible
# starting state for a container run without one.
FROM base AS dev

# NODE_ENV is deliberately NOT set here. `next dev` sets it to "development"
# itself, whereas pinning it in the image makes a `npm run build` run inside
# this container produce a production bundle against React's DEVELOPMENT
# runtime — which fails during prerendering with an unrelated-looking
# "Cannot read properties of null (reading 'useContext')".
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# `.next` must exist in the IMAGE, owned by the user that will write to it.
# docker-compose.yml mounts a named volume here, and Docker seeds a new named
# volume from whatever the image has at that path — including its ownership.
# With no such directory in the image, the volume is created owned by root and
# the non-root user below cannot write a single build artefact: `next dev`
# fails with EACCES on /app/.next.
RUN mkdir -p /app/.next

# The node images ship a non-root `node` user (uid 1000). If the dev server is
# ever compromised it does not hold root inside the container.
RUN chown -R node:node /app
USER node

EXPOSE 3000

# `next dev` binds to localhost by default, which inside a container means that
# container — unreachable from the host regardless of published ports. The
# --hostname flag is required, not cosmetic. (Same reasoning as uvicorn's
# --host 0.0.0.0 in backend/Dockerfile.)
CMD ["npm", "run", "dev"]

# --- production build --------------------------------------------------------
# Not deployed anywhere yet. It exists so that `docker compose build` proves the
# app still compiles under a real production build — type errors and lint
# failures that `next dev` tolerates are hard errors here.
FROM base AS builder

ENV NODE_ENV=production

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# --- production runtime ------------------------------------------------------
FROM base AS runner

ENV NODE_ENV=production

# Next's standalone output traces the exact files the server needs and bundles
# a minimal node_modules with them, so the runtime image carries neither the
# dev dependencies nor the source.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

USER node

EXPOSE 3000

ENV HOSTNAME=0.0.0.0 PORT=3000

CMD ["node", "server.js"]
