import json

import boto3
import pytest
from moto import mock_aws

from sovlens import report
from sovlens.catalog import Catalog
from sovlens.cli import run_scan


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-central-1")
    monkeypatch.setattr("sovlens.cli._pro", None)


def test_catalog_knows_core_services():
    cat = Catalog("eusc-de-east-1")
    assert cat.status("s3") == "ready"
    # Listed in the ESC User Guide but missing from botocore endpoint data.
    assert cat.status("route53") == "ready" and cat.status("organizations") == "ready"
    assert cat.status("cloudfront") == "wait" and "User Guide" in cat.reason("cloudfront")
    assert cat.status("globalaccelerator") == "wait"
    assert not cat.known("definitely-not-a-service")


def test_overrides(tmp_path):
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"available": [], "unavailable": ["s3"]}))
    assert Catalog("eusc-de-east-1", f).status("s3") == "wait"


def _trust(account, external_id=False):
    stmt = {"Effect": "Allow", "Action": "sts:AssumeRole", "Principal": {"AWS": f"arn:aws:iam::{account}:root"}}
    if external_id:
        stmt["Condition"] = {"StringEquals": {"sts:ExternalId": "abc"}}
    return json.dumps({"Version": "2012-10-17", "Statement": [stmt]})


@mock_aws
def test_free_scan_counts_dependencies_without_names():
    session = boto3.Session(region_name="eu-central-1")
    session.client("s3").create_bucket(
        Bucket="demo", CreateBucketConfiguration={"LocationConstraint": "eu-central-1"})
    iam = session.client("iam")
    iam.create_role(RoleName="vendor-role", AssumeRolePolicyDocument=_trust("111111111111", external_id=True))
    iam.create_role(RoleName="other-role", AssumeRolePolicyDocument=_trust("222222222222"))
    iam.create_open_id_connect_provider(Url="https://token.actions.githubusercontent.com",
                                        ClientIDList=["sts.amazonaws.com"], ThumbprintList=["a" * 40])

    result = run_scan(session, "eusc-de-east-1", ["eu-central-1"], None)

    s3 = next(s for s in result["services"] if s["service"] == "s3")
    assert s3["regions"] == ["eu-central-1"]
    counts = {d["kind"]: d["count"] for d in result["dependencies_summary"]}
    assert counts == {"third_party_trust": 1, "external_trust": 1, "identity_provider": 1}
    assert result["summary"]["outside_control"] == 2
    assert "dependencies" not in result
    page = report.to_html(result)
    assert "Sovlens Pro" in page and "vendor-role" not in page
