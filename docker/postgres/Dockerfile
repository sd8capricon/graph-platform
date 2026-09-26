# syntax=docker/dockerfile:1

# PostgreSQL 18 with Apache AGE and pgvector, built only from the official
# upstream projects. No third-party combined PostgreSQL/AGE/vector image is used.
#
# Pinned, currently supported stable releases:
#   - PostgreSQL 18.6           (docker-library/postgres, tag 18.6-trixie)
#   - Apache AGE 1.8.0 for PG18 (apache/age, tag PG18/v1.8.0-rc0, 2026-07-09)
#   - pgvector 0.8.6            (pgvector/pgvector, tag v0.8.6)
#
# The builder stage compiles both extensions against the same PostgreSQL 18
# server headers the runtime uses; only the compiled libraries and extension
# control/SQL files cross into the final image, so no toolchain ships.

ARG PG_MAJOR=18

FROM postgres:${PG_MAJOR}.6-trixie AS builder
ARG PG_MAJOR

# Bison/Flex build AGE's Cypher grammar, Perl generates its keyword list, and
# postgresql-server-dev-$PG_MAJOR provides the PGXS build infrastructure both
# extensions use.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        flex \
        bison \
        perl \
        curl \
        ca-certificates \
        "postgresql-server-dev-${PG_MAJOR}"; \
    rm -rf /var/lib/apt/lists/*

# Apache AGE 1.8.0 (PG18 branch release).
ARG AGE_VERSION=1.8.0
ARG AGE_TAG=PG18/v1.8.0-rc0
ARG AGE_SHA256=555736a31974255223778959ca8bcd9cb710b93a8fab1d846eaf3e84704b9417
RUN set -eux; \
    curl -fsSL -o /tmp/age.tar.gz \
        "https://github.com/apache/age/releases/download/${AGE_TAG}/apache-age-${AGE_VERSION}-src.tar.gz"; \
    echo "${AGE_SHA256}  /tmp/age.tar.gz" | sha256sum -c -; \
    mkdir -p /tmp/age; \
    tar -xzf /tmp/age.tar.gz -C /tmp/age --strip-components=1; \
    make -C /tmp/age -j"$(nproc)"; \
    make -C /tmp/age install DESTDIR=/stage; \
    rm -rf /tmp/age /tmp/age.tar.gz

# pgvector 0.8.6. OPTFLAGS="" avoids -march=native so the image is portable.
ARG PGVECTOR_VERSION=0.8.6
ARG PGVECTOR_SHA256=10bf9938906e5d643bbc4a7eea104b6f57ba4898e5b76b20e60484ea1d5a7f8f
RUN set -eux; \
    curl -fsSL -o /tmp/pgvector.tar.gz \
        "https://github.com/pgvector/pgvector/archive/refs/tags/v${PGVECTOR_VERSION}.tar.gz"; \
    echo "${PGVECTOR_SHA256}  /tmp/pgvector.tar.gz" | sha256sum -c -; \
    mkdir -p /tmp/pgvector; \
    tar -xzf /tmp/pgvector.tar.gz -C /tmp/pgvector --strip-components=1; \
    make -C /tmp/pgvector OPTFLAGS=""; \
    make -C /tmp/pgvector install DESTDIR=/stage; \
    rm -rf /tmp/pgvector /tmp/pgvector.tar.gz

FROM postgres:${PG_MAJOR}.6-trixie
ARG PG_MAJOR

# Only the installed extension artifacts cross the stage boundary.
COPY --from=builder /stage/usr/lib/postgresql/${PG_MAJOR}/lib/ /usr/lib/postgresql/${PG_MAJOR}/lib/
COPY --from=builder /stage/usr/share/postgresql/${PG_MAJOR}/extension/ /usr/share/postgresql/${PG_MAJOR}/extension/

# Create age and vector in POSTGRES_DB the first time the data directory is
# initialized. The Python services also create both extensions idempotently.
COPY docker/postgres/init/ /docker-entrypoint-initdb.d/
