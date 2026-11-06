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

try:
    from showcases.amnezia_arc.amnezia_adapter import (
        AmneziaAuthError,
        AmneziaClient,
        AmneziaError,
        deploy,
        load_env,
    )
except (ImportError, ModuleNotFoundError):
    from amnezia_adapter import (  # type: ignore[no-redef]
        AmneziaAuthError,
        AmneziaClient,
        AmneziaError,
        deploy,
        load_env,
    )


def main(argv: list[str] | None = None) -> int:
    env_parser = argparse.ArgumentParser(add_help=False)
    env_parser.add_argument("--env-file", help="Path to .env file")
    pre_args, _ = env_parser.parse_known_args(argv)
    loaded = load_env(pre_args.env_file)

    parser = argparse.ArgumentParser(
        description="Amnezia Hosting (my.amnezia.host) CLI: Web Login and Hardware Catalog"
    )
    parser.add_argument(
        "--env-file",
        help="Path to .env file containing AMNEZIA_EMAIL and AMNEZIA_PASSWORD",
    )
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
    parser.add_argument(
        "--deploy",
        type=int,
        metavar="PID",
        help="Deploy a VPS plan by Product ID (e.g. 15 for 'Start')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate deployment and validate checkout without placing real order",
    )
    parser.add_argument(
        "--state",
        help="Path to JSON file to persist deployment state",
    )
    parser.add_argument(
        "--max-cost-usd",
        help="Preflight budget gate limit in USD",
    )
    args = parser.parse_args(argv)

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
        print("-" * 58)
        for p in plans:
            ram_str = f"{p.ram_gb} GB"
            disk_str = f"{p.disk_gb} GB"
            price_str = f"${p.price_monthly_usd}"
            print(f" {p.product_id:<5} {p.name:<12} {p.vcpus:<6} {ram_str:<8} {disk_str:<10} {price_str:<10}")
    except AmneziaError as err:
        print(f"ERROR: Failed to fetch hardware catalog: {err}", file=sys.stderr)
        return 1

    # 2. Web Authentication Test
    print("\n[2/2] Testing authentication on my.amnezia.host...")
    if args.skip_login:
        print("Note: --skip-login specified. Skipping login test.")
        return 0

    if not (args.email and args.password):
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

        # 3. Optional Deployment Step
        if args.deploy:
            print(f"\n[3/3] Deploying VPS product ID {args.deploy} (dry_run={args.dry_run})...")
            state = deploy(
                client=client,
                product=args.deploy,
                state_path=args.state,
                dry_run=args.dry_run,
                max_cost_usd=args.max_cost_usd,
            )
            print(f"   Phase:       {state.get('phase', 'unknown')}")
            print(f"   Total:       {state.get('total_price', 'Unknown')}")
            print(f"   Message:     {state.get('message', '')}")
            if state.get("order_id"):
                print(f"   Order ID:    {state['order_id']}")
            if state.get("invoice_id"):
                print(f"   Invoice #:   {state['invoice_id']}")
                print(f"   Payment URL: {state.get('payment_url', '')}")

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
