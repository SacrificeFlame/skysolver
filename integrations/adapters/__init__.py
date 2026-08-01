"""Carrier-vendor adapter interfaces; no carrier implementation ships here."""

from integrations.adapters.base import (
    AdapterCapabilities, AdapterPage, ApprovalEvidence, CarrierAdapter,
    DeploymentCommand, PublishResult, PublishStatus,
)

__all__ = ["AdapterCapabilities", "AdapterPage", "ApprovalEvidence", "CarrierAdapter",
           "DeploymentCommand", "PublishResult", "PublishStatus"]
