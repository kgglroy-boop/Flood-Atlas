FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PROJ_NETWORK=OFF
RUN apt-get update \
    && apt-get install --no-install-recommends -y python3-gdal python3-psycopg2 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 caseworker

WORKDIR /app
COPY --chown=caseworker:caseworker backend/app/case_contract.py backend/app/case_jobs.py backend/app/case_archive.py ./
COPY --chown=caseworker:caseworker case-worker/case_worker ./case_worker
USER caseworker
ENTRYPOINT ["/usr/bin/python3", "-m", "case_worker"]
CMD ["run"]
