"""Explicit, owner-authorized control of configured SDK Gateway profiles."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.api.afi_owner_scope import PersistedOwnerScope, require_persisted_owner_scope
from app.services.service_gateway_operator import (
    ServiceGatewayOperatorControl,
    ServiceGatewayOperatorError,
)

router = APIRouter()


def _control(request: Request) -> ServiceGatewayOperatorControl:
    control = getattr(request.app.state, "service_gateway_operator_control", None)
    if not isinstance(control, ServiceGatewayOperatorControl):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "OPERATOR_NOT_CONFIGURED"},
        )
    return control


def _raise_http(error: ServiceGatewayOperatorError) -> None:
    if error.code in {"PROFILE_NOT_CONFIGURED"}:
        code = status.HTTP_404_NOT_FOUND
    elif error.code in {"OWNER_NOT_AUTHORIZED", "OPERATION_NOT_GRANTED"}:
        code = status.HTTP_403_FORBIDDEN
    elif error.code in {
        "LEGACY_MANAGER_RESTORE_IN_PROGRESS",
        "LEGACY_GATEWAY_OWNER_ACTIVE",
        "APPLICATION_OPERATION_IN_PROGRESS",
        "APPLICATION_NOT_RUNNING",
        "APPLICATION_NOT_RESTARTABLE",
    }:
        code = status.HTTP_409_CONFLICT
    else:
        code = status.HTTP_503_SERVICE_UNAVAILABLE
    raise HTTPException(
        status_code=code,
        detail={"code": error.code, "message": "Service Gateway operation was not completed."},
    ) from None


@router.get("/service-gateway/operators")
def list_service_gateway_operators(
    request: Request,
    owner: PersistedOwnerScope = Depends(require_persisted_owner_scope),
) -> dict[str, Any]:
    """List only operator profiles granted to the persisted owner."""

    try:
        return {"operators": _control(request).authorized_profiles(owner.owner_subject)}
    except ServiceGatewayOperatorError as error:
        _raise_http(error)


@router.get("/service-gateway/legacy-gateways")
def list_legacy_gateway_migration_records(
    request: Request,
    owner: PersistedOwnerScope = Depends(require_persisted_owner_scope),
) -> dict[str, Any]:
    """List exact legacy keys configured for this persisted owner only.

    The legacy credential file has no owner field, so it is never read or
    projected here. Unmapped records remain stored and are not exposed across
    owner boundaries. Starting remains an explicit action on the operator API.
    """
    control = _control(request)
    try:
        mappings = control.authorized_legacy_gateway_mappings(owner.owner_subject)
    except ServiceGatewayOperatorError as error:
        _raise_http(error)
    return {
        "gateways": [
            {
                "gateway_key": mapping["gateway_key"],
                "migration_status": "profile_available",
                "profile_ref": mapping["profile_ref"],
            }
            for mapping in mappings
        ]
    }


@router.get("/service-gateway/operators/{profile_ref}")
def read_service_gateway_operator_status(
    profile_ref: str,
    request: Request,
    owner: PersistedOwnerScope = Depends(require_persisted_owner_scope),
) -> dict[str, Any]:
    """Read finite status without constructing or starting the operator."""

    try:
        return _control(request).status(profile_ref, owner.owner_subject)
    except ServiceGatewayOperatorError as error:
        _raise_http(error)


@router.post("/service-gateway/operators/{profile_ref}/start")
def start_service_gateway_operator(
    profile_ref: str,
    request: Request,
    owner: PersistedOwnerScope = Depends(require_persisted_owner_scope),
) -> dict[str, Any]:
    """Start a trusted, configured profile after excluding mapped legacy owners."""

    try:
        return _control(request).start(profile_ref, owner.owner_subject)
    except ServiceGatewayOperatorError as error:
        _raise_http(error)


@router.post("/service-gateway/operators/{profile_ref}/recover")
def recover_service_gateway_operator(
    profile_ref: str,
    request: Request,
    owner: PersistedOwnerScope = Depends(require_persisted_owner_scope),
) -> dict[str, Any]:
    """Recover only a configured account-session operator on its owner thread."""

    try:
        return _control(request).recover(profile_ref, owner.owner_subject)
    except ServiceGatewayOperatorError as error:
        _raise_http(error)


@router.post("/service-gateway/operators/{profile_ref}/stop")
def stop_service_gateway_operator(
    profile_ref: str,
    request: Request,
    owner: PersistedOwnerScope = Depends(require_persisted_owner_scope),
) -> dict[str, Any]:
    """Stop one configured operator without releasing uncertain ownership."""

    try:
        return _control(request).stop(profile_ref, owner.owner_subject)
    except ServiceGatewayOperatorError as error:
        _raise_http(error)


@router.post("/service-gateway/operators/{profile_ref}/cleanup")
def retry_service_gateway_operator_cleanup(
    profile_ref: str,
    request: Request,
    owner: PersistedOwnerScope = Depends(require_persisted_owner_scope),
) -> dict[str, Any]:
    """Retry retained provider cleanup when the trusted grant explicitly allows it."""

    try:
        return _control(request).cleanup(profile_ref, owner.owner_subject)
    except ServiceGatewayOperatorError as error:
        _raise_http(error)
