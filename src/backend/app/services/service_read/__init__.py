"""Authorized read-only access from the application to the shared services."""

from app.services.service_read.client import (
    AccountBinding,
    AuthorizedServiceReadClient,
    MonitorBinding,
    ServiceReadUnavailableError,
)
from app.services.service_read.consumers import (
    CONSUMERS,
    ConsumerRegistryError,
    ServiceConsumer,
    consumer_for,
    validate_consumers,
)
from app.services.service_read.contracts import (
    AccountReadView,
    ReadQuality,
    ServiceReadContractError,
    StrategyHealthView,
)

__all__ = [
    "CONSUMERS",
    "AccountBinding",
    "AccountReadView",
    "AuthorizedServiceReadClient",
    "ConsumerRegistryError",
    "MonitorBinding",
    "ReadQuality",
    "ServiceConsumer",
    "ServiceReadContractError",
    "ServiceReadUnavailableError",
    "StrategyHealthView",
    "consumer_for",
    "validate_consumers",
]
