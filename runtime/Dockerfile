# AINIX runtime layer: minimal MAX inference container.
# The distro's "ART" — nothing in here but the model runner.
#
#   ACCEL=cpu     portable, builds natively on arm64 and x86_64
#   ACCEL=nvidia  adds CUDA userspace (x86_64 host with NVIDIA driver + CDI)
#   ACCEL=amd     adds ROCm userspace (x86_64 host with amdgpu + /dev/kfd)

ARG ACCEL=cpu
ARG PYTHON_VERSION=3.12

# ---------- builder ----------
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS builder

ARG MAX_EXTRAS="serve"
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    VIRTUAL_ENV=/opt/venv \
    MODULAR_HOME=/opt/venv/share/max \
    MODULAR_CACHE_DIR=/opt/venv/share/max/mojocache

RUN uv venv /opt/venv \
 && uv pip install --python /opt/venv/bin/python "max[${MAX_EXTRAS}]"

# MAX JIT-compiles its Mojo kernels on first import and needs a C compiler to
# link them. Do that here, once, so the .so cache ships inside /opt/venv and the
# runtime stage carries no toolchain at all.
RUN apt-get update \
 && apt-get install -y --no-install-recommends clang \
 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p "${MODULAR_CACHE_DIR}" \
 && /opt/venv/bin/python -c "import max.pipelines" \
 && echo "warmed:" && find "${MODULAR_CACHE_DIR}" -name '*.so' -printf '%p\n' | head

# Drop build-time-only weight: caches, tests, and headers we never execute.
RUN find /opt/venv -name '__pycache__' -prune -exec rm -rf {} + \
 && find /opt/venv -name '*.pyc' -delete \
 && rm -rf /opt/venv/share/man /opt/venv/include

# ---------- runtime ----------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

# libgomp: MAX's CPU kernels. libstdc++/libgcc come from the base image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
 && rm -rf /var/lib/apt/lists/* /usr/share/doc /usr/share/man

COPY --from=builder /opt/venv /opt/venv
COPY runtime/entry.sh /usr/local/bin/entry.sh

ENV PATH="/opt/venv/bin:${PATH}" \
    VIRTUAL_ENV=/opt/venv \
    HF_HOME=/var/cache/huggingface \
    MODULAR_HOME=/opt/venv/share/max \
    MODULAR_CACHE_DIR=/opt/venv/share/max/mojocache \
    AINIX_MODEL=unsloth/gemma-3-1b-it \
    AINIX_DEVICES=cpu \
    AINIX_PORT=8000

RUN useradd --system --uid 10001 --create-home --home-dir /home/ainix ainix \
 && mkdir -p /var/cache/huggingface /opt/venv/share/max/.max_cache \
 && chown -R ainix:ainix /var/cache/huggingface /opt/venv/share/max/.max_cache "${MODULAR_CACHE_DIR}"
USER ainix

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entry.sh"]
