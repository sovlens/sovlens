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


def test_catalog_knows_core_services():
    cat = Catalog("eusc-de-east-1")
    assert cat.status("s3") == "ready"
    assert cat.status("cloudfront") == "verify"
    assert cat.status("definitely-not-a-service") == "verify"


def test_overrides(tmp_path):
    f = tmp_path / "o.json"
    f.write_text(json.dumps({"available": [], "unavailable": ["s3"]}))
    assert Catalog("eusc-de-east-1", f).status("s3") == "wait"


@mock_aws
def test_scan_finds_services_and_iam_issues():
    session = boto3.Session(region_name="eu-central-1")
    session.client("s3").create_bucket(
        Bucket="demo", CreateBucketConfiguration={"LocationConstraint": "eu-central-1"})
    session.client("sqs").create_queue(QueueName="q")
    iam = session.client("iam")
    iam.create_policy(PolicyName="hard", PolicyDocument=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::demo/*"}]}))
    iam.create_role(RoleName="partner", AssumeRolePolicyDocument=json.dumps({
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "sts:AssumeRole",
                       "Principal": {"AWS": "arn:aws:iam::999999999999:root"}}]}))

    result = run_scan(session, "eusc-de-east-1", ["eu-central-1"], None)

    services = {s["service"]: s for s in result["services"]}
    assert services["s3"]["status"] == "ready"
    assert "sqs" in services
    # Free edition: counts only, no resource names or fixes
    assert "findings" not in result
    by_type = {f["type"]: f for f in result["findings_summary"]}
    assert by_type["hardcoded_arn"] == {"type": "hardcoded_arn", "resources": 1, "occurrences": 1}
    assert by_type["cross_account_trust"]["resources"] == 1
    page = report.to_html(result)
    assert "Sovlens Pro" in page and "partner" not in page
