"""Read-only inventory of the services an account actually uses."""
from __future__ import annotations

from collections import defaultdict

from botocore.exceptions import BotoCoreError, ClientError

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
        ec2 = session.client("ec2")
        return sorted(r["RegionName"] for r in ec2.describe_regions()["Regions"])
    except (ClientError, BotoCoreError):
        return [session.region_name] if session.region_name else []


def collect(session, regions: list[str]) -> tuple[dict, list[str]]:
    """Return ({namespace: {"count": n, "regions": set}}, warnings)."""
    usage: dict = defaultdict(lambda: {"count": 0, "regions": set()})
    warnings: list[str] = []

    def add(ns: str, region: str, n: int = 1) -> None:
        usage[ns]["count"] += n
        usage[ns]["regions"].add(region)

    # 1. Tagging API: broad, but only sees resources that are or were tagged.
    for region in regions:
        try:
            client = session.client("resourcegroupstaggingapi", region_name=region)
            for page in client.get_paginator("get_resources").paginate():
                for res in page.get("ResourceTagMappingList", []):
                    parts = res["ResourceARN"].split(":")
                    if len(parts) > 2 and parts[2]:
                        add(parts[2], region)
        except (ClientError, BotoCoreError) as exc:
            warnings.append(f"tagging API skipped in {region}: {type(exc).__name__}")

    # 2. Direct probes for core services, so untagged resources are not missed.
    seen_probe: dict[str, int] = defaultdict(int)
    for client_name, ns, op, key, is_global in PROBES:
        for region in (regions[:1] if is_global else regions):
            try:
                client = session.client(client_name, region_name=region)
                if client.can_paginate(op):
                    n = sum(len(_dig(p, key)) for p in client.get_paginator(op).paginate())
                else:
                    n = len(_dig(getattr(client, op)(), key))
            except (ClientError, BotoCoreError) as exc:
                warnings.append(f"{client_name}:{op} skipped in {region}: {type(exc).__name__}")
                continue
            if n:
                label = "global" if is_global else region
                seen_probe[ns] += n
                usage[ns]["regions"].add(label)
    # S3 buckets are regional even though the API is global.
    try:
        s3 = session.client("s3")
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
            seen_probe["s3"] = len(buckets)
    except (ClientError, BotoCoreError) as exc:
        warnings.append(f"s3:list_buckets skipped: {type(exc).__name__}")

    # Probes are exact counts; prefer them over tag-based counts for the same service.
    for ns, n in seen_probe.items():
        usage[ns]["count"] = max(usage[ns]["count"], n)

    return {k: {"count": v["count"], "regions": sorted(v["regions"])} for k, v in usage.items()}, warnings
