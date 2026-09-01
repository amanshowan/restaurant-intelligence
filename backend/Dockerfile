FROM python:3.12-slim

# PYTHONDONTWRITEBYTECODE: don't litter the bind-mounted source tree with
#   .pyc files owned by the container user.
# PYTHONUNBUFFERED: send stdout/stderr straight to the terminal so `docker
#   compose logs` shows output immediately instead of buffering it.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies are installed in their own layer, BEFORE application code is
# copied. Docker caches each layer and invalidates it only when its inputs
# change, so editing a .py file does not re-run this (slow) install step.
# Copying the whole source first would invalidate the cache on every edit.
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir '.[dev]' \
    && rm -rf build/ *.egg-info/

# Application code. In development this is overlaid by a bind mount (see
# docker-compose.yml); baking it in keeps the image self-contained and
# deployable on its own.
COPY . .

# Run as a non-root user. If the process is ever compromised, it does not
# hold root inside the container.
RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# The image's default command is the PRODUCTION one — no --reload. Local
# development overrides it in docker-compose.yml, so a dev-only flag is never
# baked into a deployable image.
#
# --host 0.0.0.0 is required, not cosmetic. Uvicorn's default of 127.0.0.1
# would bind to the loopback interface INSIDE the container, making the
# server unreachable from the host no matter what ports are published.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
