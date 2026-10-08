FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Optional database drivers, off by default. Snowflake is no longer among them —
# it has a connector of its own now, so it ships in the default dependencies; a
# connector whose every attempt ends in "no driver installed" is worse than one
# that is absent. What is left is Redshift and SQL Server, the latter also needing
# system libraries pip cannot install. A deployment that reads from one builds with
# --build-arg API_EXTRAS="[redshift]". The SQL connector checks for each driver by
# import, so an absent one is never offered rather than failing on connect.
ARG API_EXTRAS=""

# Dependencies first, so editing source doesn't reinstall them on every build.
COPY api/pyproject.toml ./
RUN pip install --no-cache-dir ".${API_EXTRAS}"

COPY api/ ./

COPY docker/api-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Never run as root: if the process is compromised, the damage stays inside
# the container rather than reaching mounted files. The entrypoint starts as
# root only to hand the hosting folders to this user, then switches to it
# before anything else runs (docker/api-entrypoint.sh).
RUN useradd --create-home --uid 1000 goalgetter && chown -R goalgetter /app

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
