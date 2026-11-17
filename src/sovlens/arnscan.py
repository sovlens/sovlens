"""Count IAM items that will not survive a partition change.

The free edition reports how many policies and roles are affected, per type.
It does not record which ones, or how to fix them.
"""
from __future__ import annotations

import json
import re

from botocore.exceptions import BotoCoreError, ClientError

ARN_RE = re.compile(r"arn:aws:[a-z0-9-]*:[a-z0-9-]*:[0-9]*:[^\"\s,\]]*")
ACCOUNT_RE = re.compile(r"(?:arn:aws:iam::)?(\d{12})(?::root)?")


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _arn_count(document: dict) -> int:
    return len(set(ARN_RE.findall(json.dumps(document))))


def _external_accounts(trust: dict, account_id: str) -> int:
    external = set()
    for stmt in _as_list((trust or {}).get("Statement")):
        principal = stmt.get("Principal") or {}
        if isinstance(principal, dict):
            for p in _as_list(principal.get("AWS")):
                m = ACCOUNT_RE.search(str(p))
                if m and m.group(1) != account_id:
                    external.add(m.group(1))
    return len(external)


def scan(session, account_id: str) -> tuple[list[dict], list[str]]:
    """Return ([{"type", "resources", "occurrences"}], warnings)."""
    totals = {
        "hardcoded_arn": {"resources": 0, "occurrences": 0},
        "cross_account_trust": {"resources": 0, "occurrences": 0},
    }
    warnings: list[str] = []
    iam = session.client("iam")

    def add(kind: str, n: int) -> None:
        if n:
            totals[kind]["resources"] += 1
            totals[kind]["occurrences"] += n

    try:
        for page in iam.get_paginator("list_policies").paginate(Scope="Local"):
            for pol in page["Policies"]:
                doc = iam.get_policy_version(
                    PolicyArn=pol["Arn"], VersionId=pol["DefaultVersionId"]
                )["PolicyVersion"]["Document"]
                add("hardcoded_arn", _arn_count(doc))
    except (ClientError, BotoCoreError) as exc:
        warnings.append(f"managed policies skipped: {type(exc).__name__}")

    try:
        for page in iam.get_paginator("list_roles").paginate():
            for role in page["Roles"]:
                if role.get("Path", "").startswith("/aws-service-role/"):
                    continue
                name = role["RoleName"]
                add("cross_account_trust", _external_accounts(role.get("AssumeRolePolicyDocument"), account_id))
                for pname in iam.list_role_policies(RoleName=name)["PolicyNames"]:
                    doc = iam.get_role_policy(RoleName=name, PolicyName=pname)["PolicyDocument"]
                    add("hardcoded_arn", _arn_count(doc))
    except (ClientError, BotoCoreError) as exc:
        warnings.append(f"roles skipped: {type(exc).__name__}")

    summary = [{"type": k, **v} for k, v in sorted(totals.items()) if v["resources"]]
    return summary, warnings
