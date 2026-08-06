#!/usr/bin/env bash
# Apply DeployGuard schema to the Aurora cluster.
#
# Prerequisites:
#   - psql installed
#   - Network access to the cluster (DeployGuard EC2 is in the same VPC after terraform apply)
#   - RDS credentials (Secrets Manager or env vars)
#
# Usage (Terraform-managed Aurora — default after infra apply):
#   export PGHOST="$(terraform -chdir=infra output -raw aurora_cluster_endpoint)"
#   export PGUSER=deployguard
#   export PGPASSWORD='...'  # from Secrets Manager deployguard-dev/database
#   ./db/apply_schema.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PGHOST="${PGHOST:?Set PGHOST to the Aurora cluster endpoint}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-deployguard}"
PGDATABASE="${PGDATABASE:-deployguard}"

echo "==> Ensuring database ${PGDATABASE} exists on ${PGHOST}"
if ! psql "postgresql://${PGUSER}@${PGHOST}:${PGPORT}/postgres" -v ON_ERROR_STOP=1 -tAc \
    "SELECT 1 FROM pg_database WHERE datname='${PGDATABASE}'" | grep -q 1; then
  psql "postgresql://${PGUSER}@${PGHOST}:${PGPORT}/postgres" -v ON_ERROR_STOP=1 \
    -c "CREATE DATABASE ${PGDATABASE}"
  echo "    created database ${PGDATABASE}"
else
  echo "    database ${PGDATABASE} already exists"
fi

echo "==> Applying schema to ${PGDATABASE}"
psql "postgresql://${PGUSER}@${PGHOST}:${PGPORT}/${PGDATABASE}" -v ON_ERROR_STOP=1 -f "${SCRIPT_DIR}/schema.sql"

echo "==> Verifying objects"
psql "postgresql://${PGUSER}@${PGHOST}:${PGPORT}/${PGDATABASE}" -v ON_ERROR_STOP=1 \
  -c "\dt" -c "SELECT total_all, unassigned_count, no_jira_count FROM fn_dashboard_stats();"

echo "Done."
