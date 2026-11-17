"""sovlens scan: read-only readiness check for the AWS European Sovereign Cloud."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import boto3

from . import __version__, arnscan, inventory, report
from .catalog import Catalog


try:  # Sovlens Pro is a separate, licensed package
    import sovlens_pro as _pro
except ImportError:
    _pro = None


def run_scan(session, target: str, regions: list[str] | None, overrides: Path | None) -> dict:
    account_id = session.client("sts").get_caller_identity()["Account"]
    regions = regions or inventory.enabled_regions(session)
    catalog = Catalog(target, overrides)
    usage, w1 = inventory.collect(session, regions)
    if _pro is not None:
        return _pro.run(session, account_id, target, catalog, usage, w1)
    summary, w2 = arnscan.scan(session, account_id)
    return report.build(account_id, target, catalog, usage, summary, w1 + w2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sovlens", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="scan the current account (read-only)")
    scan.add_argument("--profile", help="AWS CLI profile to use")
    scan.add_argument("--regions", help="comma-separated regions to scan (default: all enabled)")
    scan.add_argument("--target", default="eusc-de-east-1", help="target ESC region")
    scan.add_argument("--report", choices=["html", "json", "both"], default="both")
    scan.add_argument("--out", default="sovlens-report", help="output file name without extension")
    scan.add_argument("--overrides", default="catalog/overrides.json", help="catalog overrides file")
    args = parser.parse_args(argv)

    session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
    regions = [r.strip() for r in args.regions.split(",")] if args.regions else None
    result = run_scan(session, args.target, regions, Path(args.overrides))

    written = []
    if args.report in ("json", "both"):
        Path(f"{args.out}.json").write_text(json.dumps(result, indent=2))
        written.append(f"{args.out}.json")
    if args.report in ("html", "both"):
        page = _pro.to_html(result) if _pro is not None else report.to_html(result)
        Path(f"{args.out}.html").write_text(page)
        written.append(f"{args.out}.html")

    s = result["summary"]
    print(f"Account {result['account_id']} -> {result['target_region']}")
    print(f"  Services ready:      {s['ready']}")
    print(f"  To verify:           {s['verify']}")
    print(f"  Must wait:           {s['wait']}")
    print(f"  IAM items to change: {s['needs_changes']}")
    if result["warnings"]:
        print(f"  Warnings:            {len(result['warnings'])} (see report)")
    if s["needs_changes"] and _pro is None:
        print("  " + report.PRO_NOTE)
    print("Report: " + ", ".join(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
