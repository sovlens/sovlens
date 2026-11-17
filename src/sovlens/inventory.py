"""Read-only inventory of the services an account actually uses."""
from __future__ import annotations

from collections import defaultdict

from botocore.exceptions import BotoCoreError, ClientError

from . import runner

# (client name, ARN namespace, paginator/operation, result key, global?)
PROBES = [
    ("cloudfront", "cloudfront", "list_distributions", "DistributionList.Items", True),
    ("route53", "route53", "list_hosted_zones", "HostedZones", True),
    ("lambda", "lambda", "list_functions", "Functions", False),
    ("rds", "rds", "describe_db_instances", "DBInstances", False),
    ("dynamodb", "dynamodb", "list_tables", "TableNames", False),
    ("ecs", "ecs", "list_clusters", "clusterArns", False),
    ("eks", "eks", "list_clusters", "clusters", False),
    ("sqs", "sqs", "list_queues", "QueueUrls", False),
    ("sns", "sns", "list_topics", "Topics", False),
    ("ecr", "ecr", "describe_repositories", "repositories", False),
]


def _dig(data: dict, dotted: str):
    for part in dotted.split("."):
        data = (data or {}).get(part)
    return data or []


def enabled_regions(session) -> list[str]:
    try:
        ec2 = runner.client(session, "ec2")
        return sorted(r["RegionName"] for r in ec2.describe_regions()["Regions"])
    except (ClientError, BotoCoreError):
        return [session.region_name] if session.region_name else []


def _count(client, op: str, key: str) -> int:
    if client.can_paginate(op):
        return sum(len(_dig(p, key)) for p in client.get_paginator(op).paginate())
    return len(_dig(getattr(client, op)(), key))


def _scan_region(session, region: str, probes) -> tuple[dict, dict, list[str]]:
    tagged: dict[str, int] = defaultdict(int)
    probed: dict[str, int] = {}
    warnings: list[str] = []
    try:
        client = runner.client(session, "resourcegroupstaggingapi", region)
        for page in client.get_paginator("get_resources").paginate():
            for res in page.get("ResourceTagMappingList", []):
                parts = res["ResourceARN"].split(":")
                if len(parts) > 2 and parts[2]:
                    tagged[parts[2]] += 1
    except (ClientError, BotoCoreError) as exc:
        warnings.append(f"tagging API skipped in {region}: {type(exc).__name__}")
    for client_name, ns, op, key in probes:
        try:
            n = _count(runner.client(session, client_name, region), op, key)
        except (ClientError, BotoCoreError) as exc:
            warnings.append(f"{client_name}:{op} skipped in {region}: {type(exc).__name__}")
            continue
        if n:
            probed[ns] = n
    return dict(tagged), probed, warnings


def collect(session, regions: list[str]) -> tuple[dict, list[str]]:
    """Return ({namespace: {"count": n, "regions": [...]}}, warnings)."""
    usage: dict = defaultdict(lambda: {"count": 0, "regions": set()})
    warnings: list[str] = []
    regional = [(c, ns, op, key) for c, ns, op, key, is_global in PROBES if not is_global]
    global_probes = [(c, ns, op, key) for c, ns, op, key, is_global in PROBES if is_global]

    results = runner.for_regions(regions, lambda r: _scan_region(session, r, regional), "Inventory")
    probe_totals: dict[str, int] = defaultdict(int)
    for region, (tagged, probed, warn) in zip(regions, results):
        warnings += warn
        for ns, n in tagged.items():
            usage[ns]["count"] += n
            usage[ns]["regions"].add(region)
        for ns, n in probed.items():
            probe_totals[ns] += n
            usage[ns]["regions"].add(region)

    runner.say("Inventory: global services and S3")
    for client_name, ns, op, key in global_probes:
        try:
            n = _count(runner.client(session, client_name, regions[0] if regions else None), op, key)
        except (ClientError, BotoCoreError) as exc:
            warnings.append(f"{client_name}:{op} skipped: {type(exc).__name__}")
            continue
        if n:
            probe_totals[ns] += n
            usage[ns]["regions"].add("global")

    # S3 buckets are regional even though the API is global.
    try:
        s3 = runner.client(session, "s3")
        buckets = [b for page in s3.get_paginator("list_buckets").paginate() for b in page.get("Buckets", [])]
        for b in buckets:
            region = b.get("BucketRegion")
            if not region:
                try:
                    region = s3.get_bucket_location(Bucket=b["Name"]).get("LocationConstraint") or "us-east-1"
                except (ClientError, BotoCoreError):
                    region = "unknown"
            usage["s3"]["regions"].add(region)
        if buckets:
            probe_totals["s3"] = len(buckets)
    except (ClientError, BotoCoreError) as exc:
        warnings.append(f"s3:list_buckets skipped: {type(exc).__name__}")

    # Probes are exact counts; prefer them over tag-based counts for the same service.
    for ns, n in probe_totals.items():
        usage[ns]["count"] = max(usage[ns]["count"], n)

    return {k: {"count": v["count"], "regions": sorted(v["regions"])} for k, v in usage.items()}, warnings
