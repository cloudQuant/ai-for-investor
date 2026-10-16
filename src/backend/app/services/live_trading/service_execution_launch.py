"""Trusted bindings for a Backtrader service-v2 strategy client.

Profiles are executable deployment code loaded from the fixed entry-point
group below.  Instance JSON and strategy scripts may select neither a module
nor a service identity, account, scope, transport, or credential.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import threading
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SERVICE_STRATEGY_PROFILE_ENTRY_POINT_GROUP = "ai_for_investor.service_strategy_profiles"
SERVICE_EXECUTION_ENV_PREFIX = "AFI_SERVICE_EXECUTION_"
SERVICE_EXECUTION_PROFILE_ENV = f"{SERVICE_EXECUTION_ENV_PREFIX}PROFILE_REF"
SERVICE_EXECUTION_INSTANCE_ENV = f"{SERVICE_EXECUTION_ENV_PREFIX}INSTANCE_ID"
SERVICE_EXECUTION_SUBJECT_ENV = f"{SERVICE_EXECUTION_ENV_PREFIX}SUBJECT_REF"
SERVICE_EXECUTION_STRATEGY_ENV = f"{SERVICE_EXECUTION_ENV_PREFIX}STRATEGY_ID"
SERVICE_EXECUTION_RUN_ENV = f"{SERVICE_EXECUTION_ENV_PREFIX}RUN_ID"
SERVICE_EXECUTION_PROFILE_MAP_ENV = f"{SERVICE_EXECUTION_ENV_PREFIX}PROFILE_MAP_JSON"
SERVICE_EXECUTION_READY_ENV = f"{SERVICE_EXECUTION_ENV_PREFIX}READY_MARKER"
SERVICE_EXECUTION_STOP_COMMAND = b"STOP\n"
SERVICE_EXECUTION_READY_MARKER = "AFI_SERVICE_EXECUTION_READY"
_SERVICE_STRATEGY_PROFILE_MAP_MAX_BYTES = 16_384
_SERVICE_STRATEGY_SCRIPT_MAX_BYTES = 2_097_152
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CHILD_ENVIRONMENT_KEYS = frozenset(
    {
        "APPDATA",
        "COMSPEC",
        "HOMEDRIVE",
        "HOMEPATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LOCALAPPDATA",
        "NUMBER_OF_PROCESSORS",
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "OS",
        "PATH",
        "PATHEXT",
        "PYTHONIOENCODING",
        "PYTHONUTF8",
        "PYTHONUNBUFFERED",
        "SYSTEMDRIVE",
        "SYSTEMROOT",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "VIRTUAL_ENV",
        "WINDIR",
    }
)


class ServiceStrategyProfileError(RuntimeError):
    """Finite, non-sensitive profile and launch diagnostics."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def parse_service_strategy_profile_map(raw: object) -> dict[str, str]:
    """Parse the explicit server-owned strategy-to-profile allowlist."""

    if raw is None or raw == "":
        return {}
    if type(raw) is not str:
        raise ServiceStrategyProfileError("INVALID_PROFILE_MAP")
    try:
        encoded = raw.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise ServiceStrategyProfileError("INVALID_PROFILE_MAP") from None
    if len(encoded) > _SERVICE_STRATEGY_PROFILE_MAP_MAX_BYTES:
        raise ServiceStrategyProfileError("INVALID_PROFILE_MAP")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ServiceStrategyProfileError("INVALID_PROFILE_MAP")
            result[key] = value
        return result

    try:
        document = json.loads(raw, object_pairs_hook=unique_object)
    except (ValueError, TypeError, RecursionError):
        raise ServiceStrategyProfileError("INVALID_PROFILE_MAP") from None
    if type(document) is not dict or len(document) > 128:
        raise ServiceStrategyProfileError("INVALID_PROFILE_MAP")
    normalized: dict[str, str] = {}
    for strategy_id, profile_ref in document.items():
        if (
            type(strategy_id) is not str
            or not strategy_id
            or strategy_id != strategy_id.strip()
            or len(strategy_id) > 128
            or type(profile_ref) is not str
            or not profile_ref
            or profile_ref != profile_ref.strip()
            or len(profile_ref) > 128
        ):
            raise ServiceStrategyProfileError("INVALID_PROFILE_MAP")
        normalized[strategy_id] = profile_ref
    return normalized


@dataclass(frozen=True, slots=True)
class ServiceStrategyLaunchContext:
    """One manager-created strategy run identity, never caller-provided."""

    profile_ref: str
    instance_id: str
    subject_ref: str
    strategy_id: str
    run_id: str


@dataclass(frozen=True, slots=True)
class TrustedServiceStrategyProfile:
    """One installed code profile for an exact strategy/account authority.

    The factories are trusted deployment code. They must resolve transport
    credentials locally and return the accepted SDK config/runtime objects;
    neither callback name nor implementation is loaded from instance data.
    """

    profile_ref: str
    strategy_id: str
    script_sha256: str
    strategy_ref: str
    account_ref: str
    principal_ref: str
    owner_profile_ref: str
    intent_contract_ref: str
    service_id: str
    service_instance_id: str
    transport_ref: str
    orders_scope_ref: str
    order_query_scope_ref: str
    authorized_subjects: frozenset[str]
    legacy_gateway_keys: tuple[str, ...]
    orders_operations: frozenset[str]
    order_query_operations: frozenset[str]
    client_config_factory: Callable[[ServiceStrategyLaunchContext], Mapping[str, Any]]
    runtime_factory: Callable[[Any, ServiceStrategyLaunchContext], Any]

    def __post_init__(self) -> None:
        for field_name in (
            "profile_ref",
            "strategy_id",
            "script_sha256",
            "strategy_ref",
            "account_ref",
            "principal_ref",
            "owner_profile_ref",
            "intent_contract_ref",
            "service_id",
            "service_instance_id",
            "transport_ref",
            "orders_scope_ref",
            "order_query_scope_ref",
        ):
            value = getattr(self, field_name)
            if type(value) is not str or not value or value.strip() != value or len(value) > 128:
                raise ServiceStrategyProfileError("INVALID_TRUSTED_PROFILE")
        if (
            _SHA256_RE.fullmatch(self.script_sha256) is None
            or
            type(self.authorized_subjects) is not frozenset
            or not self.authorized_subjects
            or any(
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > 128
                for value in self.authorized_subjects
            )
            or type(self.legacy_gateway_keys) is not tuple
            or not self.legacy_gateway_keys
            or len(self.legacy_gateway_keys) > 128
            or any(
                type(value) is not str
                or not value
                or value != value.strip()
                or len(value) > 256
                for value in self.legacy_gateway_keys
            )
            or len(set(self.legacy_gateway_keys)) != len(self.legacy_gateway_keys)
            or type(self.orders_operations) is not frozenset
            or self.orders_operations != frozenset({"orders.submit", "orders.cancel"})
            or type(self.order_query_operations) is not frozenset
            or self.order_query_operations != frozenset({"orders.query"})
            or not callable(self.client_config_factory)
            or not callable(self.runtime_factory)
        ):
            raise ServiceStrategyProfileError("INVALID_TRUSTED_PROFILE")


class ServiceStrategyProfileRegistry:
    """Resolve strategy profiles from trusted installed code only."""

    def __init__(
        self,
        profiles: Iterable[TrustedServiceStrategyProfile],
        *,
        import_roots: Mapping[str, Iterable[Path]] | None = None,
    ) -> None:
        by_ref: dict[str, TrustedServiceStrategyProfile] = {}
        for profile in profiles:
            if type(profile) is not TrustedServiceStrategyProfile:
                raise ServiceStrategyProfileError("INVALID_TRUSTED_PROFILE")
            if profile.profile_ref in by_ref:
                raise ServiceStrategyProfileError("DUPLICATE_PROFILE_REF")
            by_ref[profile.profile_ref] = profile
        self._by_ref = by_ref
        self._profiles = tuple(by_ref.values())
        roots = {} if import_roots is None else dict(import_roots)
        self._import_roots = {
            profile_ref: tuple(Path(root).resolve() for root in roots.get(profile_ref, ()))
            for profile_ref in by_ref
        }

    @classmethod
    def from_entry_points(
        cls, profile_refs: Iterable[str] | None = None
    ) -> ServiceStrategyProfileRegistry:
        requested_refs = None if profile_refs is None else frozenset(profile_refs)
        if requested_refs is not None and any(
            type(value) is not str or not value or value != value.strip() or len(value) > 128
            for value in requested_refs
        ):
            raise ServiceStrategyProfileError("INVALID_PROFILE_REF")
        try:
            candidates = importlib.metadata.entry_points(
                group=SERVICE_STRATEGY_PROFILE_ENTRY_POINT_GROUP
            )
        except Exception:
            raise ServiceStrategyProfileError("PROFILE_REGISTRY_UNAVAILABLE") from None
        profiles = []
        import_roots: dict[str, tuple[Path, ...]] = {}
        loaded_refs: set[str] = set()
        for entry_point in candidates:
            if requested_refs is not None and entry_point.name not in requested_refs:
                continue
            try:
                loaded = entry_point.load()
                profile = loaded() if callable(loaded) and not isinstance(
                    loaded, TrustedServiceStrategyProfile
                ) else loaded
            except Exception:
                raise ServiceStrategyProfileError("PROFILE_LOAD_FAILED") from None
            if (
                type(profile) is not TrustedServiceStrategyProfile
                or profile.profile_ref != entry_point.name
            ):
                raise ServiceStrategyProfileError("PROFILE_ENTRY_POINT_MISMATCH")
            loaded_refs.add(entry_point.name)
            profiles.append(profile)
            distribution = getattr(entry_point, "dist", None)
            if distribution is not None:
                try:
                    root = Path(distribution.locate_file("")).resolve()
                except (OSError, RuntimeError, TypeError, ValueError):
                    raise ServiceStrategyProfileError("PROFILE_IMPORT_ROOT_UNAVAILABLE") from None
                import_roots[entry_point.name] = (root,)
        if requested_refs is not None and loaded_refs != requested_refs:
            raise ServiceStrategyProfileError("PROFILE_NOT_FOUND")
        return cls(profiles, import_roots=import_roots)

    def resolve(self, profile_ref: str) -> TrustedServiceStrategyProfile:
        if type(profile_ref) is not str or not profile_ref:
            raise ServiceStrategyProfileError("PROFILE_NOT_FOUND")
        profile = self._by_ref.get(profile_ref)
        if profile is None:
            raise ServiceStrategyProfileError("PROFILE_NOT_FOUND")
        return profile

    def import_roots(self, profile_ref: str) -> tuple[Path, ...]:
        if profile_ref not in self._by_ref:
            raise ServiceStrategyProfileError("PROFILE_NOT_FOUND")
        return self._import_roots[profile_ref]

    def resolve_for_instance(
        self,
        instance: Mapping[str, Any],
        *,
        run_id: str | None = None,
    ) -> tuple[TrustedServiceStrategyProfile, ServiceStrategyLaunchContext] | None:
        strategy_id = instance.get("strategy_id")
        if type(strategy_id) is not str or not strategy_id:
            return None
        candidates = tuple(item for item in self._profiles if item.strategy_id == strategy_id)
        if not candidates:
            return None
        instance_id = instance.get("id")
        subject_ref = instance.get("user_id")
        if (
            type(instance_id) is not str
            or not instance_id
            or type(subject_ref) is not str
            or not subject_ref
        ):
            raise ServiceStrategyProfileError("STRATEGY_SUBJECT_UNAVAILABLE")
        authorized = tuple(item for item in candidates if subject_ref in item.authorized_subjects)
        if not authorized:
            raise ServiceStrategyProfileError("STRATEGY_SUBJECT_NOT_AUTHORIZED")
        if len(authorized) != 1:
            raise ServiceStrategyProfileError("AMBIGUOUS_STRATEGY_PROFILE")
        profile = authorized[0]
        resolved_run_id = run_id or uuid.uuid4().hex
        if type(resolved_run_id) is not str or not resolved_run_id or len(resolved_run_id) > 128:
            raise ServiceStrategyProfileError("INVALID_RUN_ID")
        return profile, ServiceStrategyLaunchContext(
            profile_ref=profile.profile_ref,
            instance_id=instance_id,
            subject_ref=subject_ref,
            strategy_id=strategy_id,
            run_id=resolved_run_id,
        )

    def context_from_environment(self, environ: Mapping[str, str]) -> tuple[
        TrustedServiceStrategyProfile, ServiceStrategyLaunchContext
    ]:
        profile = self.resolve(environ.get(SERVICE_EXECUTION_PROFILE_ENV, ""))
        context = ServiceStrategyLaunchContext(
            profile_ref=profile.profile_ref,
            instance_id=environ.get(SERVICE_EXECUTION_INSTANCE_ENV, ""),
            subject_ref=environ.get(SERVICE_EXECUTION_SUBJECT_ENV, ""),
            strategy_id=environ.get(SERVICE_EXECUTION_STRATEGY_ENV, ""),
            run_id=environ.get(SERVICE_EXECUTION_RUN_ENV, ""),
        )
        if (
            context.strategy_id != profile.strategy_id
            or context.subject_ref not in profile.authorized_subjects
            or not context.instance_id
            or not context.run_id
            or len(context.instance_id) > 128
            or len(context.run_id) > 128
        ):
            raise ServiceStrategyProfileError("LAUNCH_CONTEXT_NOT_AUTHORIZED")
        return profile, context


def get_service_strategy_profile_registry(
    profile_refs: Iterable[str] | None = None,
) -> ServiceStrategyProfileRegistry:
    """Load only the requested installed-code profiles in this process."""

    return ServiceStrategyProfileRegistry.from_entry_points(profile_refs)


def build_service_strategy_environment(
    base_environment: Mapping[str, str],
    profile: TrustedServiceStrategyProfile,
    context: ServiceStrategyLaunchContext,
    *,
    backend_root: Path,
    sdk_source_root: Path | None,
    backtrader_root: Path,
    trusted_import_roots: Iterable[Path] = (),
) -> dict[str, str]:
    """Create a child environment without inheriting server configuration secrets."""

    environment = {
        key: str(value)
        for key, value in base_environment.items()
        if key in _CHILD_ENVIRONMENT_KEYS
    }
    roots: list[Path | None] = [backtrader_root, backend_root, sdk_source_root]
    roots.extend(trusted_import_roots)
    deduplicated: list[str] = []
    seen: set[str] = set()
    for root in roots:
        if root is None:
            continue
        value = str(root.resolve())
        key = os.path.normcase(value)
        if key not in seen:
            seen.add(key)
            deduplicated.append(value)
    environment["PYTHONPATH"] = os.pathsep.join(deduplicated)
    environment[SERVICE_EXECUTION_PROFILE_ENV] = profile.profile_ref
    environment[SERVICE_EXECUTION_INSTANCE_ENV] = context.instance_id
    environment[SERVICE_EXECUTION_SUBJECT_ENV] = context.subject_ref
    environment[SERVICE_EXECUTION_STRATEGY_ENV] = context.strategy_id
    environment[SERVICE_EXECUTION_RUN_ENV] = context.run_id
    environment[SERVICE_EXECUTION_READY_ENV] = f"{SERVICE_EXECUTION_READY_MARKER}:{context.run_id}"
    return environment


def validate_profile_owner_grant(
    profile: TrustedServiceStrategyProfile,
    raw_operator_deployment: object,
    subject_ref: str,
) -> None:
    """Bind the strategy profile to its exact separately configured SDK owner."""

    if (
        type(raw_operator_deployment) is not str
        or not raw_operator_deployment
        or type(subject_ref) is not str
        or subject_ref not in profile.authorized_subjects
    ):
        raise ServiceStrategyProfileError("SERVICE_OWNER_GRANT_UNAVAILABLE")
    try:
        document = json.loads(raw_operator_deployment, object_pairs_hook=_unique_object)
    except (ValueError, TypeError, RecursionError):
        raise ServiceStrategyProfileError("SERVICE_OWNER_GRANT_INVALID") from None
    if (
        type(document) is not dict
        or set(document) != {"schema_version", "operators"}
        or type(document.get("schema_version")) is not int
        or document["schema_version"] != 1
        or type(document.get("operators")) is not list
    ):
        raise ServiceStrategyProfileError("SERVICE_OWNER_GRANT_INVALID")
    matches = [
        grant
        for grant in document["operators"]
        if isinstance(grant, Mapping)
        and grant.get("profile_ref") == profile.owner_profile_ref
    ]
    if len(matches) != 1:
        raise ServiceStrategyProfileError("SERVICE_OWNER_GRANT_MISMATCH")
    grant = matches[0]
    expected_keys = {
        "profile_ref",
        "account_ref",
        "authorized_subjects",
        "operations",
        "auto_start",
        "legacy_gateway_keys",
    }
    subjects = grant.get("authorized_subjects")
    operations = grant.get("operations")
    keys = grant.get("legacy_gateway_keys")
    if (
        set(grant) != expected_keys
        or grant.get("account_ref") != profile.account_ref
        or type(subjects) is not list
        or any(type(item) is not str for item in subjects)
        or len(set(subjects)) != len(subjects)
        or subject_ref not in subjects
        or type(operations) is not list
        or any(type(item) is not str for item in operations)
        or len(set(operations)) != len(operations)
        or not {"status", "start", "stop"} <= set(operations)
        or type(grant.get("auto_start")) is not bool
        or type(keys) is not list
        or any(type(item) is not str for item in keys)
        or len(set(keys)) != len(keys)
        or set(keys) != set(profile.legacy_gateway_keys)
        or profile.owner_profile_ref == profile.profile_ref
    ):
        raise ServiceStrategyProfileError("SERVICE_OWNER_GRANT_MISMATCH")
    try:
        from bt_api_py.gateway_operator_application import GatewayOperatorProfileRegistry

        owner_profile = GatewayOperatorProfileRegistry.from_entry_points().resolve(
            profile.owner_profile_ref
        )
    except Exception:
        raise ServiceStrategyProfileError("SERVICE_OWNER_PROFILE_UNAVAILABLE") from None
    if getattr(owner_profile, "role", None) != "account_session_worker":
        raise ServiceStrategyProfileError("SERVICE_OWNER_PROFILE_MISMATCH")


def validate_profile_strategy_source(
    profile: TrustedServiceStrategyProfile,
    script_path: Path,
) -> bytes:
    """Read one bounded exact strategy source bound by the trusted profile."""

    if not script_path.is_file():
        raise ServiceStrategyProfileError("STRATEGY_SOURCE_UNAVAILABLE")
    try:
        source = script_path.read_bytes()
    except OSError:
        raise ServiceStrategyProfileError("STRATEGY_SOURCE_UNAVAILABLE") from None
    if len(source) > _SERVICE_STRATEGY_SCRIPT_MAX_BYTES:
        raise ServiceStrategyProfileError("STRATEGY_SOURCE_INVALID")
    if hashlib.sha256(source).hexdigest() != profile.script_sha256:
        raise ServiceStrategyProfileError("STRATEGY_SOURCE_NOT_AUTHORIZED")
    return source


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ServiceStrategyProfileError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def validate_profile_client_config(
    profile: TrustedServiceStrategyProfile,
    context: ServiceStrategyLaunchContext,
    raw_config: Mapping[str, Any],
) -> Any:
    """Parse and bind the narrow exact SDK order/query client route contract."""

    try:
        from bt_api_py.service_config import parse_client_config

        parsed = parse_client_config(dict(raw_config))
        public = parsed.to_public_dict()
    except Exception as error:
        code = getattr(error, "code", None)
        if type(code) is str and code.isidentifier():
            raise ServiceStrategyProfileError(f"CLIENT_CONFIG_{code}") from None
        raise ServiceStrategyProfileError("CLIENT_CONFIG_INVALID") from None
    if parsed.process_role != "strategy_client":
        raise ServiceStrategyProfileError("CLIENT_CONFIG_ROLE_MISMATCH")
    registration = public.get("registration")
    if not isinstance(registration, Mapping) or registration.get("strategy_ref") != profile.strategy_ref:
        raise ServiceStrategyProfileError("CLIENT_CONFIG_STRATEGY_MISMATCH")
    clients = public.get("clients")
    execution = clients.get("execution") if isinstance(clients, Mapping) else None
    settings = execution.get("settings") if isinstance(execution, Mapping) else None
    bindings = settings.get("bindings") if isinstance(settings, Mapping) else None
    if type(bindings) is not list or len(bindings) != 2:
        raise ServiceStrategyProfileError("CLIENT_CONFIG_BINDINGS_MISMATCH")
    by_mount: dict[str, Mapping[str, Any]] = {}
    for binding in bindings:
        if not isinstance(binding, Mapping):
            raise ServiceStrategyProfileError("CLIENT_CONFIG_BINDINGS_MISMATCH")
        mount = binding.get("mount")
        if mount not in {"broker.orders", "broker.order_query"} or mount in by_mount:
            raise ServiceStrategyProfileError("CLIENT_CONFIG_BINDINGS_MISMATCH")
        by_mount[str(mount)] = binding
    expected = {
        "broker.orders": profile.orders_scope_ref,
        "broker.order_query": profile.order_query_scope_ref,
    }
    if set(by_mount) != set(expected):
        raise ServiceStrategyProfileError("CLIENT_CONFIG_BINDINGS_MISMATCH")
    for mount, scope_ref in expected.items():
        binding = by_mount[mount]
        if (
            binding.get("service_id") != profile.service_id
            or binding.get("instance_id") != profile.service_instance_id
            or binding.get("scope_ref") != scope_ref
            or binding.get("account_ref") != profile.account_ref
            or binding.get("transport_ref") != profile.transport_ref
            or binding.get("required") is not True
        ):
            raise ServiceStrategyProfileError("CLIENT_CONFIG_BINDINGS_MISMATCH")
    return parsed


def validate_profile_runtime(
    profile: TrustedServiceStrategyProfile,
    context: ServiceStrategyLaunchContext,
    runtime: Any,
    parsed_config: Any | None = None,
) -> Any:
    """Reject any runtime whose code-bound identity/run differs from the profile."""

    try:
        from bt_api_base.service_protocol import WireRole
        from bt_api_py.service_runtime import ServiceClientRuntime
    except ImportError:
        raise ServiceStrategyProfileError("SERVICE_SDK_UNAVAILABLE") from None
    identity = getattr(runtime, "identity", None)
    if (
        type(runtime) is not ServiceClientRuntime
        or runtime.state != "new"
        or runtime.run_id != context.run_id
        or identity is None
        or identity.role is not WireRole.STRATEGY_CLIENT
        or identity.principal_ref != profile.principal_ref
        or identity.actor_ref != profile.strategy_ref
        or (
            parsed_config is not None
            and getattr(runtime, "_config", None) != parsed_config.to_public_dict()
        )
        or getattr(runtime, "_requested_operations", None)
        != {
            "broker.orders": profile.orders_operations,
            "broker.order_query": profile.order_query_operations,
        }
    ):
        raise ServiceStrategyProfileError("RUNTIME_IDENTITY_MISMATCH")
    return runtime


def run_profiled_strategy_script(
    script_path: Path,
    profile: TrustedServiceStrategyProfile,
    context: ServiceStrategyLaunchContext,
    *,
    stop_reader: Callable[[Callable[[], None]], None],
) -> None:
    """Run the approved strategy source with normal managed SDK session ownership."""

    import sys

    try:
        import backtrader as bt
        from backtrader.stores.service_execution_session import run_configured_cerebro
    except ImportError:
        raise ServiceStrategyProfileError("BACKTRADER_SERVICE_EXECUTION_UNAVAILABLE") from None
    source = validate_profile_strategy_source(profile, script_path)
    try:
        import ast

        syntax_tree = ast.parse(source, filename=str(script_path))
        declared_contracts = []
        for statement in syntax_tree.body:
            if isinstance(statement, ast.Assign) and any(
                isinstance(target, ast.Name)
                and target.id == "AFI_SERVICE_INTENT_CONTRACT_REF"
                for target in statement.targets
            ):
                declared_contracts.append(statement.value)
            elif (
                isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
                and statement.target.id == "AFI_SERVICE_INTENT_CONTRACT_REF"
            ):
                declared_contracts.append(statement.value)
        if (
            len(declared_contracts) != 1
            or not isinstance(declared_contracts[0], ast.Constant)
            or type(declared_contracts[0].value) is not str
            or declared_contracts[0].value != profile.intent_contract_ref
        ):
            raise ServiceStrategyProfileError("INTENT_CONTRACT_MISMATCH")
        code = compile(syntax_tree, str(script_path), "exec")
    except (SyntaxError, UnicodeError, ValueError):
        raise ServiceStrategyProfileError("STRATEGY_SOURCE_INVALID") from None

    original_run = bt.Cerebro.run
    started = threading.Event()
    stop_requested = threading.Event()
    runtime_holder: list[Any] = []
    invoked = False
    active_cerebro: list[Any] = []

    class _ManagedStopSignal(bt.Strategy):
        def start(self) -> None:
            started.set()
            sys.stdout.write(f"{SERVICE_EXECUTION_READY_MARKER}:{context.run_id}\n")
            sys.stdout.flush()
            if stop_requested.is_set() and active_cerebro:
                active_cerebro[-1].runstop()

        def next(self) -> None:
            return None

    def request_stop() -> None:
        stop_requested.set()
        if started.is_set() and active_cerebro:
            active_cerebro[-1].runstop()

    stop_reader(request_stop)

    def managed_run(cerebro: Any, **run_kwargs: Any) -> Any:
        nonlocal invoked
        if script_namespace.get("AFI_SERVICE_INTENT_CONTRACT_REF") != profile.intent_contract_ref:
            raise ServiceStrategyProfileError("INTENT_CONTRACT_MISMATCH")
        if invoked:
            raise ServiceStrategyProfileError("MULTIPLE_CEREBRO_RUNS_UNSUPPORTED")
        invoked = True
        raw_config = profile.client_config_factory(context)
        if not isinstance(raw_config, Mapping):
            raise ServiceStrategyProfileError("CLIENT_CONFIG_INVALID")
        parsed = validate_profile_client_config(profile, context, raw_config)

        def create_runtime(parsed_config: Any) -> Any:
            if parsed_config.fingerprint() != parsed.fingerprint():
                raise ServiceStrategyProfileError("CLIENT_CONFIG_CHANGED")
            runtime = profile.runtime_factory(parsed_config, context)
            runtime_holder.append(validate_profile_runtime(profile, context, runtime, parsed_config))
            return runtime

        cerebro.addstrategy(_ManagedStopSignal)
        active_cerebro.append(cerebro)
        bt.Cerebro.run = original_run
        try:
            result = run_configured_cerebro(
                cerebro,
                raw_config,
                runtime_factory=create_runtime,
                **run_kwargs,
            )
        finally:
            bt.Cerebro.run = managed_run
            active_cerebro.clear()
        runtime = runtime_holder[-1] if runtime_holder else None
        if (
            runtime is None
            or runtime.state != "closed"
            or runtime.unregister_uncertainties != 0
        ):
            raise ServiceStrategyProfileError("SERVICE_EXECUTION_CLOSE_UNCERTAIN")
        return result

    bt.Cerebro.run = managed_run
    previous_argv = sys.argv
    previous_path = list(sys.path)
    script_namespace = {
        "__name__": "__main__",
        "__file__": str(script_path),
        "__cached__": None,
        "__doc__": None,
        "__loader__": None,
        "__package__": None,
        "__spec__": None,
        "__builtins__": __builtins__,
    }
    try:
        sys.argv = [str(script_path)]
        sys.path.insert(0, str(script_path.parent))
        exec(code, script_namespace, script_namespace)
    finally:
        bt.Cerebro.run = original_run
        sys.argv = previous_argv
        sys.path[:] = previous_path
    if not invoked:
        raise ServiceStrategyProfileError("CEREBRO_MANAGED_RUN_REQUIRED")
