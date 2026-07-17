#!/bin/bash
# Creates generic catalog + data-plane databases for local sharding tests.
# Runs once on first Postgres volume init (docker-entrypoint-initdb.d).
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
  CREATE DATABASE efficientai_catalog;
  CREATE DATABASE efficientai_data_01;
  CREATE DATABASE efficientai_data_02;
  CREATE DATABASE efficientai_data_03;
EOSQL
