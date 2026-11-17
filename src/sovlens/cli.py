"""sovlens scan: read-only readiness check for the AWS European Sovereign Cloud."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from . import __version__, deps, inventory, report, runner
from .catalog import Catalog

try:  # Sovlens Pro is a separate, licensed package
    import sovlens_pro as _pro
except ImportError:
    _pro = None


def run_scan(session, target: str, regions: list[str] | None, overrides: Path | None,
             iac: Path | None = None) -> dict:
    runner.say("Checking credentials")
    account_id = runner.client(session, "sts").get_caller_identity()["Account"]
    regions = regions or inventory.enabled_regions(session)
    runner.say(f"Account {account_id}, {len(regions)} regions")
    catalog = Catalog(target, overrides)
    usage, w1 = inventory.collect(session, regions)
    if _pro is not None:
        return _pro.run(session, account_id, target, catalog, usage, w1, regions=regions, iac=iac)
    summary, w2, _org = deps.scan(session, account_id)
    return report.build(account_id, target, catalog, usage, summary, w1 + w2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sovlens", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    scan = sub.add_parser("scan", help="scan the current account (read-only)")
    scan.add_argument("--profile", help="AWS CLI profile to use")
    scan.add_argument("--regions", help="comma-separated regions to scan (default: all enabled)")
    scan.add_argument("--target", default="eusc-de-east-1", help="target ESC region")
    scan.add_argument("--iac", help="folder with Terraform or CloudFormation code to check (Sovlens Pro)")
    scan.add_argument("--report", choices=["html", "json", "both"], default="both")
    scan.add_argument("--out", default="sovlens-report", help="output file name without extension")
    scan.add_argument("--quiet", action="store_true", help="no progress output")
    scan.add_argument("--overrides", default="catalog/overrides.json", help="catalog overrides file")
    args = parser.parse_args(argv)

    runner.set_quiet(args.quiet)
    iac = Path(args.iac) if args.iac else None
    if iac is not None and _pro is None:
        print("Note: --iac is part of Sovlens Pro (https://sovlens.dev). Skipping the code check.")
        iac = None
    elif iac is not None and not iac.is_dir():
        print(f"Error: --iac folder not found: {iac}", file=sys.stderr)
        return 2

    try:
        session = boto3.Session(profile_name=args.profile) if args.profile else boto3.Session()
        regions = [r.strip() for r in args.regions.split(",")] if args.regions else None
        result = run_scan(session, args.target, regions, Path(args.overrides), iac)
    except BotoCoreError as exc:
        print(f"Error: could not use your AWS credentials: {exc}", file=sys.stderr)
        print("If you signed in with 'aws login', run: pip install \"botocore[crt]\"", file=sys.stderr)
        return 1
    except ClientError as exc:
        print(f"Error: AWS rejected the request: {exc}", file=sys.stderr)
        return 1

    runner.say("Writing report")
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
    print(f"  Services ready:                    {s['ready']}")
    print(f"  To verify:                         {s['verify']}")
    print(f"  Must wait:                         {s['wait']}")
    print(f"  Dependencies outside your control: {s['outside_control']}")
    print(f"  All cross-partition dependencies:  {s['dependencies']}")
    if result["warnings"]:
        print(f"  Warnings:                          {len(result['warnings'])} (see report)")
    if _pro is None:
        print("  Sovlens Pro lists each one with a fix: https://sovlens.dev")
    print("Report: " + ", ".join(written))
    return 0


if __name__ == "__main__":
    sys.exit(main())
