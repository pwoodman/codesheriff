# The Code Sheriff — batteries-included image.
# Build: docker build -t codesheriff .
# Run: docker run --rm -v "$PWD:/repo" -w /repo codesheriff run --skip review
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates nodejs npm shellcheck yamllint \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY configs ./configs
COPY tooling/js/package.json tooling/js/package-lock.json tooling/js/eslint.config.js ./tooling_js_stub/
RUN pip install --no-cache-dir ".[all]" \
  && npm install -g prettier eslint jscpd \
  && codesheriff --help >/dev/null

WORKDIR /repo
ENTRYPOINT ["codesheriff"]
CMD ["run", "--skip", "review"]
