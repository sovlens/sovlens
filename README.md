# Sovlens

Read-only readiness scanner for the AWS European Sovereign Cloud (ESC).

It answers one question: **what in this AWS account will not move to the ESC partition as-is?**

- Lists the services you actually use and checks each against the target region.
- Counts dependencies that cross the partition boundary, whether your resources were built with Terraform, CloudFormation or the console:
  - roles trusted by third-party vendors (roles with an ExternalId) and by accounts outside your organization,
  - roles trusted by other accounts in your organization,
  - membership in an AWS Organization,
  - SAML and OIDC identity providers.
- Writes a local HTML and JSON report. Nothing leaves your machine.

Not affiliated with Amazon Web Services. Technical readiness only, not legal or compliance advice.

## Quick start

Requires Python 3.10 or newer.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install .
sovlens scan --profile my-profile
open sovlens-report.html
```

Options: `--regions eu-central-1,eu-west-1`, `--target eusc-de-east-1`, `--report html|json|both`, `--out name`, `--quiet` (no progress output). Regions are scanned in parallel; a full scan of all enabled regions usually takes a few minutes.

## Permissions

Read-only. The minimal policy is in `iam/sovlens-readonly-policy.json`. `ReadOnlyAccess` or `SecurityAudit` also work. Run from the organization's management account to tell your own accounts from external ones.

## How the verdicts work

| Status | Meaning |
| --- | --- |
| Ready | The service has an endpoint in the target region. |
| Verify | No endpoint listed, or a global/edge service. Check AWS Capabilities by Region. |
| Wait | Marked unavailable in `catalog/overrides.json`. |

Dependencies are grouped as **Outside your control** (a vendor or another company must act), **Rebuild in the sovereign cloud** (you recreate it in ESC) and **Code to change** (Pro, from your Terraform or CloudFormation files).

The service catalog comes from the service list in the [AWS European Sovereign Cloud User Guide](https://docs.aws.eu/esc/latest/userguide/services.html) (`src/sovlens/data/esc_services.json`, with the date it was checked). Widely used services the guide does not cover, such as CloudFront, are "Wait". The endpoint data shipped with botocore is a fallback only: it has no entry for partition-wide services such as IAM, Organizations and Route 53. Anything not covered by either is "Verify", never "Wait". Add confirmed corrections to `catalog/overrides.json`.

## Free and Pro

This repository is the free edition. Sovlens Pro is a separate add-on: install it next to this package and the same `sovlens scan` command produces the full report.

| | Free (this repo) | Pro |
| --- | --- | --- |
| Scope | One account | Whole organization, all regions |
| Services | Verdict per service | Plus feature-level parity |
| Dependencies | Number per type | Every resource with a fix |
| Resource policies (S3, KMS, SQS, SNS) | No | Yes |
| S3 replication, Lambda layers, network links | No | Yes |
| Terraform and CloudFormation code (`--iac`) | No | Yes |
| Report | HTML, JSON | HTML, JSON, PDF |

## Known limits (v0.2)

- Service-level only. Feature-level parity (instance types, engine versions, individual APIs) is not checked yet.
- Inventory uses the tagging API plus direct probes for core services. Never-tagged resources of other services can be missed.
- Single account. Organization-wide scanning is not built yet.

## Development

```sh
pip install -e ".[dev]"
pytest
```
