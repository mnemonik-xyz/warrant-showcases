# syntax=docker/dockerfile:1@sha256:4edf897a3ffa55b89f906fc8cc78afdb3f1834cc9c7083565e611a8a7d5fe99e
#
# Seller MCP server image (showcases/ionet_arc/seller_mcp_server.py).
#
# Build from the repository root with BuildKit (required: the per-Dockerfile
# ignore file Dockerfile.dockerignore depends on it):
#
#   DOCKER_BUILDKIT=1 docker build -f showcases/ionet_arc/Dockerfile -t warrant-seller:dev .
#
# warrant-host and warrant-policy come from the Warrant core release named in
# core.lock. scripts/fetch_core.py downloads them and checks every SHA-256 digest
# against the lock; the build fails on a mismatch. warrant-host is published for
# linux x86_64 only, so build this image for linux/amd64.
#
# Base images are pinned by multi-arch index digest; apt packages are not
# pinned, so a digest pins the base layer only. Bump deliberately before a
# mainnet rebuild: docker buildx imagetools inspect <tag> --format '{{json .Manifest.Digest}}'
# and replace the digest after the tag in each FROM line (and in the syntax line).
#
# Secrets (IO_NET_API_KEY, the seller key) are runtime-only:
# env file and read-only mount. Never pass them as build arguments.

# ---- binaries from the pinned core release (core.lock), verified by SHA-256
FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55 AS bins
ARG DEBIAN_FRONTEND=noninteractive
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY core.lock ./
COPY scripts/fetch_core.py scripts/
RUN WARRANT_CORE_DIR=/core python3 scripts/fetch_core.py fetch \
    && install -D -m 0755 /core/bin/warrant-host /out/warrant-host \
    && install -D -m 0755 /core/bin/warrant-policy /out/warrant-policy

# ---- Python virtual environment from requirements.txt only
FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55 AS python-deps
ARG DEBIAN_FRONTEND=noninteractive
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY showcases/ionet_arc/requirements.txt /tmp/requirements.txt
# Record the resolved set before pip itself is pruned, then strip pip and bytecode.
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --disable-pip-version-check -r /tmp/requirements.txt \
    && /opt/venv/bin/pip freeze --disable-pip-version-check > /opt/pip-freeze.txt \
    && /opt/venv/bin/pip uninstall -y --disable-pip-version-check pip \
    && find /opt/venv -name __pycache__ -type d -prune -exec rm -rf {} + \
    && find /opt/venv -name '*.pyc' -delete

# ---- runtime
FROM ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55 AS runtime
ARG DEBIAN_FRONTEND=noninteractive
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# UID/GID 10001 is fixed: the deploy role default warrant_canary_seller_uid
# matches it and owns the secret files by it. Change both together.
# The stock ubuntu user (UID 1000) is removed; nothing runs as it.
RUN userdel --remove ubuntu \
    && groupadd --gid 10001 seller \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /nonexistent \
        --shell /usr/sbin/nologin seller \
    && install -d -o root -g root -m 0755 /app/showcases/ionet_arc /usr/share/warrant-seller \
    && install -d -o 10001 -g 10001 -m 0700 /var/lib/warrant-seller

COPY --from=bins --chmod=0755 /out/warrant-host /out/warrant-policy /usr/local/bin/
# Fail the build, not the VM run, on a wrong-arch, Mach-O or broken binary. Both
# print their usage and exit 1 without arguments, so assert the text, not the code
# (pipefail would turn that designed exit 1 into a failure, hence DL4006 ignored).
# hadolint ignore=DL4006
RUN warrant-policy 2>&1 | grep -q 'Usage: warrant-policy' \
    && warrant-host 2>&1 | grep -q 'Usage: warrant-host'
COPY --from=python-deps /opt/venv /opt/venv
COPY --from=python-deps --chmod=0644 /opt/pip-freeze.txt /usr/share/warrant-seller/pip-freeze.txt

# Explicit list: only the modules the seller imports. REPO_ROOT (parents[2] of
# the server file) resolves to /app, so the manifest's checkout-relative paths
# resolve under the config mount /app/showcases/ionet_arc/config (read-only).
COPY --chmod=0644 \
    showcases/ionet_arc/__init__.py \
    showcases/ionet_arc/seller_mcp_server.py \
    showcases/ionet_arc/adapter.py \
    showcases/ionet_arc/escrow.py \
    /app/showcases/ionet_arc/

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    IONET_STATE_DIR=/var/lib/warrant-seller

USER 10001:10001
WORKDIR /app
EXPOSE 8000

# Port-only probe: no credential belongs in the image.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python3", "-c", "import os, socket; socket.create_connection(('127.0.0.1', int(os.environ.get('PORT', '8000'))), 3).close()"]

CMD ["python", "-m", "showcases.ionet_arc.seller_mcp_server"]
