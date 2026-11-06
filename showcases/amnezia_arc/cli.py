#!/usr/bin/env python3
"""Amnezia Hosting (my.amnezia.host) CLI: Web Login and Hardware Discovery.

Usage:
    export AMNEZIA_EMAIL="your_email@example.com"
    export AMNEZIA_PASSWORD="your_password"
    python showcases/amnezia_arc/cli.py

Or pass directly:
    python showcases/amnezia_arc/cli.py --email <email> --password <password>
"""

from __future__ import annotations

import argparse
import os
import sys

from amnezia_adapter import AmneziaAuthError, AmneziaClient, AmneziaError, load_env


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Amnezia Hosting (my.amnezia.host) CLI: Web Login and Hardware Catalog"
    )
    parser.add_argument(
        "--env-file",
        help="Path to .env file containing AMNEZIA_EMAIL and AMNEZIA_PASSWORD",
    )
    # Parse env-file first so environment variables are populated
    pre_args, _ = parser.parse_known_args()
    loaded = load_env(pre_args.env_file)

    parser.add_argument(
        "--email",
        default=os.environ.get("AMNEZIA_EMAIL"),
        help="Email address for my.amnezia.host (default: $AMNEZIA_EMAIL)",
    )
    parser.add_argument(
        "--password",
        default=os.environ.get("AMNEZIA_PASSWORD"),
        help="Password for my.amnezia.host (default: $AMNEZIA_PASSWORD)",
    )
    parser.add_argument(
        "--skip-login",
        action="store_true",
        help="Skip login and only list public hardware catalog",
    )
    args = parser.parse_args()

    client = AmneziaClient()

    print("=" * 72)
    print(" Amnezia Hosting (my.amnezia.host) — PoC Automation")
    print("=" * 72)
    if loaded:
        print("[*] Loaded environment credentials from .env")

    # 1. Hardware Catalog Discovery
    print("\n[1/2] Fetching available VPS hardware catalog...")
    try:
        plans = client.list_hardware()
        print(f"Found {len(plans)} VPS tiers in Netherlands (EU-AMS):\n")
        print(f" {'PID':<5} {'Plan':<12} {'vCPU':<6} {'RAM':<8} {'Disk':<10} {'Price/Mo':<10}")
        print("-" * 55)
        for p in plans:
            print(
                f" {p.product_id:<5} {p.name:<12} {p.vcpus:<6} "
                f"{p.ram_gb} GB{'':<3} {p.disk_gb} GB{'':<4} ${p.price_monthly_usd:<9}"
            )
    except AmneziaError as err:
        print(f"ERROR: Failed to fetch hardware catalog: {err}", file=sys.stderr)
        return 1

    # 2. Web Authentication Test
    print("\n[2/2] Testing authentication on my.amnezia.host...")
    if args.skip_login or not (args.email and args.password):
        print("Note: AMNEZIA_EMAIL / AMNEZIA_PASSWORD not set. Skipping login test.")
        print("To test login, rerun with:")
        print("  export AMNEZIA_EMAIL='user@example.com' AMNEZIA_PASSWORD='...'")
        print("  python showcases/amnezia_arc/cli.py")
        return 0

    print(f"Attempting login as: {args.email} ...")
    try:
        account = client.login(args.email, args.password)
        print(" SUCCESS: Authenticated successfully!")
        if account.name:
            print(f"   Name:           {account.name}")
        print(f"   Credit Balance: {account.credit_balance}")
        print(f"   Active VPSs:    {account.active_services}")

        # List any existing services
        services = client.list_services()
        if services:
            print(f"\n Active/Pending Services ({len(services)}):")
            for s in services:
                print(f"   - ID: {s['service_id']} | Name: {s['name']} | Status: {s['status']}")
        else:
            print("\n No active VPS services found on this account.")

    except AmneziaAuthError as err:
        print(f" FAILED: {err}", file=sys.stderr)
        return 2
    except AmneziaError as err:
        print(f" ERROR: {err}", file=sys.stderr)
        return 3

    print("\n" + "=" * 72)
    print(" PoC Completed Successfully.")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
