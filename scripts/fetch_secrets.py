#!/usr/bin/env python3
"""Fetch DeployGuard app credentials from AWS Secrets Manager.

Example:
    python scripts/fetch_secrets.py \\
      --secret-arn arn:aws:secretsmanager:us-east-1:657246005217:secret:deployguard-dev/app-credentials-t99KAJ

Prints env var names loaded (never prints secret values).
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.secrets import fetch_app_credentials, load_secrets_into_env

DEFAULT_SECRET_ARN = (
    "arn:aws:secretsmanager:us-east-1:657246005217:secret:deployguard-dev/app-credentials-t99KAJ"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Load DeployGuard credentials from Secrets Manager")
    parser.add_argument(
        "--secret-arn",
        default=os.environ.get("SECRETS_MANAGER_SECRET_ARN", DEFAULT_SECRET_ARN),
        help="Secrets Manager secret name or ARN",
    )
    parser.add_argument("--region", default=os.environ.get("AWS_REGION", "us-east-1"))
    parser.add_argument(
        "--export-env",
        action="store_true",
        help="Inject fetched values into the current process environment",
    )
    args = parser.parse_args()

    try:
        if args.export_env:
            credentials = load_secrets_into_env(args.secret_arn, args.region)
        else:
            credentials = fetch_app_credentials(args.secret_arn, args.region)
    except Exception as exc:
        print(f"Failed to fetch secret: {exc}", file=sys.stderr)
        return 1

    if not credentials:
        print("No credentials found in secret payload.", file=sys.stderr)
        return 1

    print(f"Loaded from {args.secret_arn}:")
    for key in sorted(credentials):
        print(f"  {key}=***")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
