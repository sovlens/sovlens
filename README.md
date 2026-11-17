# Sovlens

Read-only readiness scanner for the AWS European Sovereign Cloud (ESC).

It answers one question: **what in this AWS account will not move to the ESC partition as-is?**

- Lists the services you actually use and checks each against the target region.
- Counts hardcoded `arn:aws:` references in IAM policies and IAM roles that trust other accounts (roles cannot be assumed across partitions).
- Writes a local HTML and JSON report. Nothing leaves your machine.

Not affiliated with Amazon Web Services. Technical readiness only, not legal or compliance advice.

## Quick start

```sh
pip install .
sovlens scan --profile my-profile
open sovlens-report.html
```

Options: `--regions eu-central-1,eu-west-1`, `--target eusc-de-east-1`, `--report html|json|both`, `--out name`.

## Permissions

Read-only. The minimal policy is in `iam/sovlens-readonly-policy.json`. `ReadOnlyAccess` or `SecurityAudit` also work.

## How the verdicts work

| Status | Meaning |
| --- | --- |
| Ready | The service has an endpoint in the target region. |
| Verify | No endpoint listed, or a global/edge service. Check AWS Capabilities by Region. |
| Wait | Marked unavailable in `catalog/overrides.json`. |

The catalog comes from the endpoint data shipped with botocore, so keep boto3 up to date. botocore can lag behind launches, which is why a missing service is "Verify", not "Wait". Add confirmed corrections to `catalog/overrides.json`.

## Free and Pro

This repository is the free edition. Sovlens Pro is a separate add-on: install it next to this package and the same `sovlens scan` command produces the full report.

| | Free (this repo) | Pro |
| --- | --- | --- |
| Scope | One account | Whole organization, all regions |
| Services | Verdict per service | Plus feature-level parity |
| IAM | Number of findings | Full list with fixes |
| Resource policies (S3, KMS, SQS) | No | Yes |
| Report | HTML, JSON | HTML, JSON, PDF |

## Known limits (v0.1)

- Service-level only. Feature-level parity (instance types, engine versions, individual APIs) is not checked yet.
- Inventory uses the tagging API plus direct probes for 11 core services. Never-tagged resources of other services can be missed.
- Single account. Organization-wide scanning is not built yet.
- IAM scan covers customer-managed policies, inline role policies and role trust. The free edition reports counts only.

## Development

```sh
pip install -e ".[dev]"
pytest
```
