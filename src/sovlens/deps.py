"""Dependencies that cross the partition boundary.

The AWS European Sovereign Cloud is a separate partition. Roles, policies and
connections that point at accounts or services in the commercial partition
will not work from there, whether the resources were built with Terraform,
CloudFormation or the console.

This module holds the shared helpers and the checks of the free edition, which
reports counts only. Sovlens Pro adds resource policies, replication, network
links, Lambda layers and infrastructure-as-code checks, with resource names and
fixes.
"""
from __future__ import annotations

import re

from botocore.exceptions import BotoCoreError, ClientError

from . import runner

ACCOUNT_RE = re.compile(r"(?<!\d)(\d{12})(?!\d)")

# Groups shown in reports, in this order.
GROUPS = {
    "outside_control": "Outside your control",
    "rebuild": "Rebuild in the sovereign cloud",
    "code": "Code to change",
}

KINDS = {
    "third_party_trust": ("outside_control", "Third-party integration (role with ExternalId)"),
    "external_trust": ("outside_control", "Role trusted by an account outside your organization"),
    "external_resource_policy": ("outside_control", "Resource policy grants an outside account"),
    "cross_account_replication": ("outside_control", "S3 replication to another account"),
    "external_layer": ("outside_control", "Lambda layer from another account"),
    "external_network": ("outside_control", "Network link to another account"),
    "org_trust": ("rebuild", "Role trusted by another account in your organization"),
    "org_membership": ("rebuild", "Account belongs to an AWS Organization"),
    "identity_provider": ("rebuild", "SAML or OIDC identity provider"),
    "private_link": ("rebuild", "Direct Connect or VPN connection"),
    "hardcoded_arn": ("code", "Hardcoded arn:aws: in infrastructure code"),
}


def as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


class OrgContext:
    """Which accounts count as 'yours'."""

    def __init__(self, session, account_id: str):
        self.account_id = account_id
        self.accounts: set[str] = {account_id}
        self.in_org = False
        self.complete = True
        self.warnings: list[str] = []
        try:
            org = runner.client(session, "organizations").describe_organization()["Organization"]
            self.in_org = True
            self.accounts.add(org["MasterAccountId"])
        except (ClientError, BotoCoreError):
            return
        try:
            client = runner.client(session, "organizations")
            for page in client.get_paginator("list_accounts").paginate():
                self.accounts |= {a["Id"] for a in page["Accounts"]}
        except (ClientError, BotoCoreError):
            self.complete = False
            self.warnings.append(
                "Organization accounts could not be listed. Run from the management account "
                "to tell your own accounts from external ones."
            )

    def is_own(self, account: str) -> bool:
        return account in self.accounts


def principal_accounts(principal) -> list[str]:
    """12-digit account IDs named in an IAM principal block. '*' is returned as '*'."""
    if principal == "*":
        return ["*"]
    if not isinstance(principal, dict):
        return []
    found = []
    for p in as_list(principal.get("AWS")):
        if p == "*":
            found.append("*")
            continue
        m = ACCOUNT_RE.search(str(p))
        if m:
            found.append(m.group(1))
    return found


def has_external_id(statement: dict) -> bool:
    cond = statement.get("Condition") or {}
    for operator in cond.values():
        if isinstance(operator, dict) and any(k.lower() == "sts:externalid" for k in operator):
            return True
    return False


def role_trust_findings(session, org: OrgContext) -> tuple[list[dict], list[str]]:
    """One finding per (role, trusted account). Used by both editions."""
    findings: list[dict] = []
    warnings: list[str] = []
    try:
        iam = runner.client(session, "iam")
        for page in iam.get_paginator("list_roles").paginate():
            for role in page["Roles"]:
                if role.get("Path", "").startswith("/aws-service-role/"):
                    continue
                doc = role.get("AssumeRolePolicyDocument") or {}
                for stmt in as_list(doc.get("Statement")):
                    if stmt.get("Effect") != "Allow":
                        continue
                    for account in principal_accounts(stmt.get("Principal")):
                        if account == org.account_id:
                            continue
                        if has_external_id(stmt):
                            kind = "third_party_trust"
                        elif account != "*" and org.is_own(account):
                            kind = "org_trust"
                        else:
                            kind = "external_trust"
                        findings.append({"kind": kind, "resource": f"role/{role['RoleName']}",
                                         "detail": f"trusts {account}"})
    except (ClientError, BotoCoreError) as exc:
        warnings.append(f"IAM roles skipped: {type(exc).__name__}")
    return findings, warnings


def identity_findings(session, org: OrgContext) -> tuple[list[dict], list[str]]:
    findings: list[dict] = []
    warnings: list[str] = []
    if org.in_org:
        findings.append({"kind": "org_membership", "resource": "account",
                         "detail": "member of an AWS Organization"})
    try:
        iam = runner.client(session, "iam")
        for p in iam.list_saml_providers().get("SAMLProviderList", []):
            findings.append({"kind": "identity_provider", "resource": p["Arn"].split(":", 5)[-1],
                             "detail": "SAML provider"})
        for p in iam.list_open_id_connect_providers().get("OpenIDConnectProviderList", []):
            findings.append({"kind": "identity_provider", "resource": p["Arn"].split(":", 5)[-1],
                             "detail": "OIDC provider"})
    except (ClientError, BotoCoreError) as exc:
        warnings.append(f"identity providers skipped: {type(exc).__name__}")
    return findings, warnings


def summarize(findings: list[dict]) -> list[dict]:
    """Counts per kind, without resource names. The free edition only keeps this."""
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["kind"]] = counts.get(f["kind"], 0) + 1
    order = list(KINDS)
    return [{"kind": k, "group": KINDS[k][0], "count": counts[k]}
            for k in sorted(counts, key=order.index)]


def scan(session, account_id: str) -> tuple[list[dict], list[str], OrgContext]:
    """Free edition: counts of role trust and identity dependencies."""
    runner.say("Dependencies: organization, roles and identity providers")
    org = OrgContext(session, account_id)
    trust, w1 = role_trust_findings(session, org)
    ident, w2 = identity_findings(session, org)
    return summarize(trust + ident), org.warnings + w1 + w2, org
