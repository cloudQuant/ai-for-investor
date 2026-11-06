"""Deployment-owned read-only service, gateway, monitor and portfolio grants.

Deployment-owned service composition documents. Each value carries client
authentication material, so ``repr=False, exclude=True`` keeps it out of
settings reprs and ordinary model dumps; an empty value keeps the
integration off.

Extracted verbatim from :class:`app.config.Settings`: same field names,
annotations, defaults, constraint metadata and validators. The composed
:class:`app.config.Settings` collects the sections in repository order, so a
field's env-var name is unchanged, and pydantic collects a ``field_validator``
declared on a section mixin and runs it on the composed model.

No behaviour lives here: these are settings declarations only.
"""

from pydantic import Field, SecretStr, field_validator


class ServiceDeploymentSecretsMixin:
    """Deployment-owned read-only service, gateway, monitor and portfolio grants."""

    # Optional, deployment-owned read-only service-client composition. This
    # value contains client authentication material and is never exposed by
    # settings reprs or ordinary model dumps. Empty keeps the integration off.
    SERVICE_READ_DEPLOYMENT_JSON: SecretStr = Field(
        default=SecretStr(""),
        repr=False,
        exclude=True,
        description=(
            "Secret deployment JSON for explicitly authorized read-only service clients; "
            "leave blank to keep service reads unconfigured"
        ),
    )

    # Trusted, server-owned SDK Gateway profiles. The document selects only
    # code-registered profiles and exact owner grants; it contains no factory,
    # endpoint or credential material.
    SERVICE_GATEWAY_OPERATOR_DEPLOYMENT_JSON: SecretStr = Field(
        default=SecretStr(""),
        repr=False,
        exclude=True,
        description=(
            "Secret exact-scope deployment for trusted service-v2 Gateway operator profiles; "
            "leave blank to keep operator lifecycle control disabled"
        ),
    )

    # Separate operator-owned issuer and authenticated client grant for
    # owner-side monitoring controls. This never inherits read-service grants.
    SERVICE_MONITOR_CONTROL_DEPLOYMENT_JSON: SecretStr = Field(
        default=SecretStr(""),
        repr=False,
        exclude=True,
        description=(
            "Secret exact-scope deployment for signed monitor owner controls; "
            "leave blank to keep owner controls disabled"
        ),
    )

    # Separate, operator-owned grants for exact strategy-run reductions.
    # Requests can name an approved target but cannot choose account/run/order
    # terms or client credentials.
    SERVICE_STRATEGY_REDUCTION_DEPLOYMENT_JSON: SecretStr = Field(
        default=SecretStr(""),
        repr=False,
        exclude=True,
        description=(
            "Secret exact-run deployment for approved strategy reductions; "
            "leave blank to keep owner.reduce disabled"
        ),
    )

    # Server-owned exact instrument/FX joins for the portfolio's display-only
    # market inputs. This configuration cannot grant market-data access; every
    # query still passes through the authenticated v2 authorization path.
    PORTFOLIO_VALUATION_BINDINGS_JSON: SecretStr = Field(
        default=SecretStr(""),
        repr=False,
        exclude=True,
        description="Bounded deployment-owned exact valuation input bindings",
    )

    @field_validator("SERVICE_READ_DEPLOYMENT_JSON")
    @classmethod
    def validate_service_read_deployment_size(cls, value: SecretStr) -> SecretStr:
        """Keep the secret deployment document bounded before JSON parsing."""
        if len(value.get_secret_value().encode("utf-8")) > 262_144:
            raise ValueError("SERVICE_READ_DEPLOYMENT_JSON exceeds the 256 KiB limit")
        return value

    @field_validator("SERVICE_GATEWAY_OPERATOR_DEPLOYMENT_JSON")
    @classmethod
    def validate_service_gateway_operator_deployment_size(cls, value: SecretStr) -> SecretStr:
        """Bound the trusted operator profile grant document before parsing."""
        if len(value.get_secret_value().encode("utf-8")) > 262_144:
            raise ValueError("SERVICE_GATEWAY_OPERATOR_DEPLOYMENT_JSON exceeds the 256 KiB limit")
        return value

    @field_validator("SERVICE_MONITOR_CONTROL_DEPLOYMENT_JSON")
    @classmethod
    def validate_service_monitor_control_deployment_size(cls, value: SecretStr) -> SecretStr:
        """Bound the separate operator-owned monitor control deployment."""
        if len(value.get_secret_value().encode("utf-8")) > 262_144:
            raise ValueError("SERVICE_MONITOR_CONTROL_DEPLOYMENT_JSON exceeds the 256 KiB limit")
        return value

    @field_validator("SERVICE_STRATEGY_REDUCTION_DEPLOYMENT_JSON")
    @classmethod
    def validate_service_strategy_reduction_deployment_size(cls, value: SecretStr) -> SecretStr:
        """Bound the operator-owned exact-run reduction deployment."""
        if len(value.get_secret_value().encode("utf-8")) > 262_144:
            raise ValueError("SERVICE_STRATEGY_REDUCTION_DEPLOYMENT_JSON exceeds the 256 KiB limit")
        return value

    @field_validator("PORTFOLIO_VALUATION_BINDINGS_JSON")
    @classmethod
    def validate_portfolio_valuation_bindings_size(cls, value: SecretStr) -> SecretStr:
        """Bound the startup-owned exact instrument and FX crosswalk document."""
        if len(value.get_secret_value().encode("utf-8")) > 262_144:
            raise ValueError("PORTFOLIO_VALUATION_BINDINGS_JSON exceeds the 256 KiB limit")
        return value
