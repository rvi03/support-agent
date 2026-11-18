# Postgres 17 with pgvector and pg_textsearch (BM25) built from pinned tags (D16).
# X4 fallback: if pg_textsearch stops building, switch BM25 to ParadeDB pg_search
# behind the same knowledge server and record it in decisions.md.
ARG PG_IMAGE=postgres:17.12-bookworm

FROM ${PG_IMAGE} AS build
ARG PGVECTOR_TAG=v0.8.7
ARG PG_TEXTSEARCH_TAG=v1.5.1
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential git ca-certificates \
      postgresql-server-dev-17 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git clone --depth 1 --branch "${PGVECTOR_TAG}" https://github.com/pgvector/pgvector.git \
 && make -C pgvector OPTFLAGS="" \
 && make -C pgvector install
RUN git clone --depth 1 --branch "${PG_TEXTSEARCH_TAG}" https://github.com/timescale/pg_textsearch.git \
 && make -C pg_textsearch \
 && make -C pg_textsearch install

FROM ${PG_IMAGE}
COPY --from=build /usr/lib/postgresql/17/lib/ /usr/lib/postgresql/17/lib/
COPY --from=build /usr/share/postgresql/17/extension/ /usr/share/postgresql/17/extension/
