"""Which services exist in the target partition.

Source of truth for v0.1: the endpoint data shipped with botocore, plus manual
overrides. botocore's data can lag behind real launches, so a service that is
not listed is reported as "verify", never as a hard "no".
"""
from __future__ import annotations

import json
from pathlib import Path

import botocore
import botocore.session

TARGET_PARTITION = "aws-eusc"

# Services that are operated outside a single regional endpoint in the
# commercial partition. Their presence always deserves a manual look.
GLOBAL_SERVICES = {"cloudfront", "route53", "globalaccelerator", "shield", "waf"}


class Catalog:
    def __init__(self, target_region: str, overrides_path: Path | None = None):
        self.target_region = target_region
        self.botocore_version = botocore.__version__
        self._session = botocore.session.get_session()
        self._available: set[str] = set()
        self._known: set[str] = set()
        self._build()
        self.override_available: set[str] = set()
        self.override_unavailable: set[str] = set()
        if overrides_path and overrides_path.exists():
            data = json.loads(overrides_path.read_text())
            self.override_available = set(data.get("available", []))
            self.override_unavailable = set(data.get("unavailable", []))

    def _namespaces(self, service_name: str) -> set[str]:
        """ARN namespaces a botocore service can appear under."""
        names = {service_name}
        try:
            meta = self._session.get_service_model(service_name).metadata
        except Exception:
            return names
        for key in ("signingName", "endpointPrefix"):
            if meta.get(key):
                names.add(meta[key])
        return names

    def _build(self) -> None:
        for svc in self._session.get_available_services():
            names = self._namespaces(svc)
            self._known |= names
            regions = self._session.get_available_regions(
                svc, partition_name=TARGET_PARTITION
            )
            if self.target_region in regions:
                self._available |= names

    def status(self, namespace: str) -> str:
        """Return 'ready', 'wait' or 'verify' for an ARN service namespace."""
        if namespace in self.override_unavailable:
            return "wait"
        if namespace in self.override_available:
            return "ready"
        if namespace in GLOBAL_SERVICES:
            return "verify"
        if namespace in self._available:
            return "ready"
        return "verify"

    def reason(self, namespace: str) -> str:
        if namespace in self.override_unavailable:
            return "Marked unavailable in catalog overrides"
        if namespace in self.override_available:
            return "Marked available in catalog overrides"
        if namespace in GLOBAL_SERVICES:
            return "Global or edge service: check how it is offered in the target partition"
        if namespace in self._available:
            return f"Endpoint listed for {self.target_region}"
        if namespace in self._known:
            return f"No endpoint listed for {self.target_region} in botocore {self.botocore_version}: verify against AWS Capabilities by Region"
        return "Service not recognised: verify manually"
