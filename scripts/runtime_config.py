#!/usr/bin/env python3
"""Select, validate, and snapshot issue-to-merge runtime routing."""

from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CONFIG_SCHEMA_VERSION = 2
SELECTION_SCHEMA_VERSION = 1
SNAPSHOT_SCHEMA_VERSION = 1
TIERS = ("simple", "normal", "complex", "extreme")
THINKING_LEVELS = {
    "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"
}
ROOT = Path(__file__).resolve().parents[1]


class ConfigError(ValueError):
    """Raised when runtime selection data violates the portable contract."""


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{field} must be an object")
    return value


def _nonempty(value: Any, field: str, *, allow_null: bool = False) -> None:
    if value is None and allow_null:
        return
    if not isinstance(value, str) or not value.strip():
        suffix = " or null" if allow_null else ""
        raise ConfigError(f"{field} must be a non-empty string{suffix}")


def _integer(value: Any, field: str, minimum: int, maximum: int | None = None) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigError(f"{field} must be an integer >= {minimum}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{field} must be an integer <= {maximum}")


def read_json(path: str | Path, description: str) -> dict[str, Any]:
    source = Path(path)
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"cannot read {description} {source}: {exc}") from exc
    if not isinstance(value, dict):
        raise ConfigError(f"{description} root must be an object")
    return value


def write_json(path: str | Path, value: dict[str, Any], *, overwrite: bool = True) -> None:
    target = Path(path).resolve()
    if target.exists() and not overwrite:
        raise ConfigError(f"refusing to overwrite existing file: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _validate_route(route: Any, field: str, runtime: str, *, read_only: bool = False) -> None:
    value = _mapping(route, field)
    _nonempty(value.get("role"), f"{field}.role")
    if runtime == "codex":
        _nonempty(value.get("model"), f"{field}.model", allow_null=True)
        reasoning = value.get("reasoning")
        if reasoning is not None and reasoning not in THINKING_LEVELS:
            raise ConfigError(
                f"{field}.reasoning must be null or one of: {', '.join(sorted(THINKING_LEVELS))}"
            )
    else:
        for name in ("profile", "provider", "model"):
            _nonempty(value.get(name), f"{field}.{name}", allow_null=True)
        present = [value.get(name) is not None for name in ("profile", "provider", "model")]
        if any(present) and not all(present):
            raise ConfigError(f"{field} must inherit or set profile/provider/model together")
    if read_only:
        if value.get("read_only") is not True:
            raise ConfigError(f"{field}.read_only must be true")
        if value.get("fork_turns") != "none":
            raise ConfigError(f"{field}.fork_turns must be 'none'")


def validate_config(config: dict[str, Any], expected_runtime: str | None = None) -> None:
    if config.get("schema_version") != CONFIG_SCHEMA_VERSION:
        raise ConfigError(f"schema_version must be {CONFIG_SCHEMA_VERSION}")
    runtime = config.get("runtime")
    if runtime not in {"codex", "hermes"}:
        raise ConfigError("runtime must be codex or hermes")
    if expected_runtime is not None and runtime != expected_runtime:
        raise ConfigError(f"configuration runtime is {runtime!r}, expected {expected_runtime!r}")
    _nonempty(config.get("preset_id"), "preset_id", allow_null=True)
    _nonempty(config.get("label"), "label")
    strategy = config.get("selection_strategy")
    if strategy not in {"current", "tiered", "custom"}:
        raise ConfigError("selection_strategy must be current, tiered, or custom")

    roles = _mapping(config.get("roles"), "roles")
    for name in ("manager", "worker", "reviewer", "remote_phase"):
        if name not in roles:
            raise ConfigError(f"roles.{name} is required")
    _validate_route(roles["manager"], "roles.manager", runtime)
    worker = _mapping(roles["worker"], "roles.worker")
    tiers = _mapping(worker.get("tiers"), "roles.worker.tiers")
    required_tiers = TIERS if runtime == "codex" else TIERS[:3]
    if set(tiers) != set(required_tiers):
        raise ConfigError(
            f"roles.worker.tiers must contain exactly: {', '.join(required_tiers)}"
        )
    for tier in required_tiers:
        _validate_route(tiers[tier], f"roles.worker.tiers.{tier}", runtime)
    _validate_route(roles["reviewer"], "roles.reviewer", runtime, read_only=True)
    remote = _mapping(roles["remote_phase"], "roles.remote_phase")
    if remote != {"reuse_worker": True}:
        raise ConfigError("roles.remote_phase must contain only reuse_worker=true")

    for name in ("researcher", "explorer", "senior_reviewer", "judge", "architect"):
        if name in roles:
            _validate_route(
                roles[name],
                f"roles.{name}",
                runtime,
                read_only=name in {"reviewer", "senior_reviewer", "judge", "architect"},
            )

    constraints = _mapping(config.get("constraints"), "constraints")
    max_children = constraints.get("max_children")
    if max_children is not None:
        _integer(max_children, "constraints.max_children", 1)
    if constraints.get("fast_mode") not in {True, False, None}:
        raise ConfigError("constraints.fast_mode must be true, false, or null")
    if runtime == "hermes":
        if constraints.get("nested_delegation") not in {True, None}:
            raise ConfigError("constraints.nested_delegation must be true or null")
        depth = constraints.get("max_spawn_depth")
        if depth is not None:
            _integer(depth, "constraints.max_spawn_depth", 2)

    policy = _mapping(config.get("policy"), "policy")
    _nonempty(policy.get("id"), "policy.id")
    for name in ("strict_lifecycle", "assessment_required", "local_pass_required"):
        if not isinstance(policy.get(name), bool):
            raise ConfigError(f"policy.{name} must be a boolean")
    _integer(policy.get("review_limit"), "policy.review_limit", 1, 15)
    if policy["strict_lifecycle"]:
        if runtime != "codex":
            raise ConfigError("strict_lifecycle is supported by Codex routing")
        for role_name in (
            "manager", "reviewer", "researcher", "explorer",
            "senior_reviewer", "judge", "architect"
        ):
            if role_name not in roles:
                raise ConfigError(f"strict policy requires roles.{role_name}")
        judge_policy = _mapping(policy.get("judge"), "policy.judge")
        if judge_policy.get("failed_review_cycles") != 2:
            raise ConfigError("policy.judge.failed_review_cycles must be 2")
        for trigger in ("reviewer_disagreement", "architecture_security_uncertainty"):
            if judge_policy.get(trigger) is not True:
                raise ConfigError(f"policy.judge.{trigger} must be true")
        if not policy["assessment_required"] or not policy["local_pass_required"]:
            raise ConfigError(
                "strict_lifecycle requires assessment_required and local_pass_required"
            )
        for name, route in (
            ("roles.manager", roles["manager"]),
            ("roles.reviewer", roles["reviewer"]),
            ("roles.judge", roles["judge"]),
            *((f"roles.worker.tiers.{tier}", tiers[tier]) for tier in TIERS),
        ):
            if route.get("model") is None or route.get("reasoning") is None:
                raise ConfigError(f"{name} must select an explicit model and reasoning")
    else:
        enabled = [
            name
            for name in ("assessment_required", "local_pass_required")
            if policy[name]
        ]
        if enabled:
            fields = ", ".join(f"policy.{name}" for name in enabled)
            raise ConfigError(
                f"{fields} must be false when policy.strict_lifecycle is false"
            )
        if "judge" in policy:
            raise ConfigError(
                "policy.judge must be omitted when policy.strict_lifecycle is false"
            )


def load_config(path: str | Path, expected_runtime: str | None = None) -> dict[str, Any]:
    config = read_json(path, "runtime config")
    validate_config(config, expected_runtime)
    return config


def current_config(runtime: str) -> dict[str, Any]:
    if runtime == "codex":
        inherited = lambda role: {"role": role, "model": None, "reasoning": None}
        tiers = {
            tier: inherited("worker" if tier in {"simple", "normal"} else
                            "senior_worker" if tier == "complex" else "expert_worker")
            for tier in TIERS
        }
        roles: dict[str, Any] = {
            "manager": inherited("manager"),
            "worker": {"tiers": tiers},
            "reviewer": {**inherited("reviewer"), "read_only": True, "fork_turns": "none"},
            "remote_phase": {"reuse_worker": True},
        }
    else:
        inherited_hermes = lambda role: {
            "role": role, "profile": None, "provider": None, "model": None
        }
        roles = {
            "manager": inherited_hermes("manager"),
            "worker": {"tiers": {tier: inherited_hermes("worker") for tier in TIERS[:3]}},
            "reviewer": {
                **inherited_hermes("reviewer"), "read_only": True, "fork_turns": "none"
            },
            "remote_phase": {"reuse_worker": True},
        }
    config = {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "preset_id": None,
        "label": f"Use current {runtime} settings",
        "runtime": runtime,
        "selection_strategy": "current",
        "roles": roles,
        "constraints": {
            "max_children": None,
            "fast_mode": None,
            **({"nested_delegation": True, "max_spawn_depth": 2} if runtime == "hermes" else {}),
        },
        "policy": {
            "id": f"{runtime}-current-v1",
            "strict_lifecycle": False,
            "assessment_required": False,
            "local_pass_required": False,
            "review_limit": 15,
        },
    }
    validate_config(config, runtime)
    return config


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge mappings recursively; explicit null is a value, not absence."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_selection(path: str | Path) -> dict[str, Any]:
    selection = read_json(path, "selection")
    if selection.get("selection_schema_version") != SELECTION_SCHEMA_VERSION:
        raise ConfigError(
            f"selection_schema_version must be {SELECTION_SCHEMA_VERSION}"
        )
    runtime = selection.get("runtime")
    if runtime not in {"codex", "hermes"}:
        raise ConfigError("selection runtime must be codex or hermes")
    config = _mapping(selection.get("effective_config"), "effective_config")
    validate_config(config, runtime)
    if config["runtime"] != runtime:
        raise ConfigError("selection runtime does not match effective_config")
    strategy = selection.get("strategy")
    if strategy not in {"current", "tiered", "custom"}:
        raise ConfigError("selection strategy must be current, tiered, or custom")
    if config["selection_strategy"] != strategy:
        raise ConfigError("selection strategy does not match effective_config")
    _nonempty(selection.get("selected_at"), "selected_at")
    preset_path = selection.get("preset_path")
    if strategy == "tiered":
        _nonempty(preset_path, "preset_path")
    elif preset_path is not None:
        raise ConfigError("preset_path is valid only for a tiered selection")
    return selection


def select_runtime(
    selection_path: str | Path,
    runtime: str,
    strategy: str,
    config_path: str | Path | None = None,
    capabilities_path: str | Path | None = None,
) -> dict[str, Any]:
    current_preview: dict[str, Any] | None = None
    if strategy == "current":
        if config_path is not None:
            raise ConfigError("--config is only valid with --strategy custom")
        if capabilities_path is None:
            raise ConfigError(
                "--capabilities is required to preview inspected current settings before saving"
            )
        config = current_config(runtime)
        current_preview = preview_current(runtime, capabilities_path)
        preset_path = None
    elif strategy == "tiered":
        if capabilities_path is not None:
            raise ConfigError("--capabilities is used only with --strategy current")
        if runtime != "codex":
            raise ConfigError("the shipped tiered strategy is available only for codex")
        preset = Path(config_path) if config_path else ROOT / "config" / "runtimes" / "codex.json"
        config = load_config(preset, runtime)
        if config["selection_strategy"] != "tiered":
            raise ConfigError("tiered selection requires a tiered runtime preset")
        preset_path = str(preset.resolve())
    elif strategy == "custom":
        if capabilities_path is not None:
            raise ConfigError("--capabilities is used only with --strategy current")
        if config_path is None:
            raise ConfigError("--config is required with --strategy custom")
        config = load_config(config_path, runtime)
        config = copy.deepcopy(config)
        config["selection_strategy"] = "custom"
        config["preset_id"] = None
        config["label"] = f"Custom {runtime} routing"
        validate_config(config, runtime)
        preset_path = None
    else:
        raise ConfigError("strategy must be current, tiered, or custom")
    selection = {
        "selection_schema_version": SELECTION_SCHEMA_VERSION,
        "selected_at": now_utc(),
        "runtime": runtime,
        "strategy": strategy,
        "preset_path": preset_path,
        "effective_config": config,
        "current_preview": current_preview,
    }
    write_json(selection_path, selection)
    return selection


def resolve_selection(
    selection_path: str | Path | None,
    explicit_config_path: str | Path | None = None,
    override_path: str | Path | None = None,
) -> dict[str, Any]:
    selection: dict[str, Any] | None = None
    if selection_path and Path(selection_path).is_file():
        selection = load_selection(selection_path)
    elif selection_path and Path(selection_path).exists():
        raise ConfigError(f"selection path is not a file: {Path(selection_path)}")

    explicit = load_config(explicit_config_path) if explicit_config_path else None
    if selection is None and explicit is None:
        return {
            "status": "setup_required",
            "message": "Choose current settings, the tiered Codex preset, or a custom config.",
            "options": runtime_options(),
        }

    preset_path: str | None = None
    if selection and selection.get("preset_path"):
        preset_path = selection["preset_path"]
    saved_config = selection["effective_config"] if selection else {}
    effective = copy.deepcopy(saved_config)
    if explicit is not None:
        if effective and explicit["runtime"] != effective["runtime"]:
            raise ConfigError("explicit config runtime does not match saved selection")
        effective = deep_merge(effective, explicit)
    if override_path:
        override = read_json(override_path, "override")
        if "runtime" in override and override["runtime"] != effective.get("runtime"):
            raise ConfigError("override runtime does not match selected runtime")
        effective = deep_merge(effective, override)
    validate_config(effective)
    return {
        "status": "resolved",
        "runtime": effective["runtime"],
        "policy_version": effective["policy"]["id"],
        "effective_config": effective,
        "sources": {
            "preset": preset_path,
            "saved_selection": str(Path(selection_path).resolve()) if selection else None,
            "explicit_config": (
                str(Path(explicit_config_path).resolve()) if explicit_config_path else None
            ),
            "override": str(Path(override_path).resolve()) if override_path else None,
        },
    }


def _route_pairs(config: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    roles = config["roles"]
    pairs = [("manager", roles["manager"]), ("reviewer", roles["reviewer"])]
    pairs.extend(
        (f"worker.{tier}", route)
        for tier, route in roles["worker"]["tiers"].items()
    )
    pairs.extend(
        (name, roles[name])
        for name in ("researcher", "explorer", "senior_reviewer", "judge", "architect")
        if name in roles
    )
    return pairs


def _route_from_roles(roles: dict[str, Any], name: str) -> dict[str, Any]:
    if name.startswith("worker."):
        tier = name.split(".", 1)[1]
        return _mapping(
            _mapping(roles.get("worker"), "current_routes.worker")
            .get("tiers", {})
            .get(tier),
            f"current_routes.worker.tiers.{tier}",
        )
    return _mapping(roles.get(name), f"current_routes.{name}")


def resolve_dispatch_config(
    config: dict[str, Any], capabilities: dict[str, Any]
) -> dict[str, Any]:
    """Bind inherited route/limit fields to inspected values for one Issue."""
    resolved = copy.deepcopy(config)
    runtime = resolved["runtime"]
    fields = (
        ("model", "reasoning")
        if runtime == "codex"
        else ("profile", "provider", "model")
    )
    needs_current_routes = any(
        route.get(field) is None
        for _, route in _route_pairs(resolved)
        for field in fields
    )
    current_roles: dict[str, Any] = {}
    if needs_current_routes:
        current_roles = _mapping(
            capabilities.get("current_routes"), "capabilities.current_routes"
        )
    for name, route in _route_pairs(resolved):
        if not any(route.get(field) is None for field in fields):
            continue
        actual = _route_from_roles(current_roles, name)
        actual_role = actual.get("role")
        _nonempty(actual_role, f"current_routes.{name}.role")
        if actual_role != route.get("role"):
            raise ConfigError(
                f"current {name}.role does not reflect the selected role"
            )
        for field in fields:
            actual_value = actual.get(field)
            _nonempty(actual_value, f"current_routes.{name}.{field}")
            selected_value = route.get(field)
            if selected_value is not None and selected_value != actual_value:
                raise ConfigError(
                    f"current {name}.{field} does not reflect the selected explicit value"
                )
            route[field] = actual_value

    host_max = capabilities.get("max_children")
    _integer(host_max, "capabilities.max_children", 1)
    configured_max = resolved["constraints"].get("max_children")
    resolved["constraints"]["max_children"] = (
        min(configured_max, host_max) if configured_max else host_max
    )
    configured_fast = resolved["constraints"].get("fast_mode")
    if runtime == "codex":
        host_fast = capabilities.get("fast_mode")
        if not isinstance(host_fast, bool):
            raise ConfigError("capabilities.fast_mode must be a boolean for Codex")
        if configured_fast is not None and configured_fast is not host_fast:
            raise ConfigError(
                f"selected config requires fast_mode={str(configured_fast).lower()} on the host"
            )
        resolved["constraints"]["fast_mode"] = (
            host_fast if configured_fast is None else configured_fast
        )
    elif configured_fast is not None:
        host_fast = capabilities.get("fast_mode")
        if not isinstance(host_fast, bool) or host_fast is not configured_fast:
            raise ConfigError(
                f"selected config requires fast_mode={str(configured_fast).lower()} on the host"
            )
    validate_config(resolved, runtime)
    return resolved


def preview_current(runtime: str, capabilities_path: str | Path) -> dict[str, Any]:
    capabilities = read_json(capabilities_path, "host capabilities")
    config = resolve_dispatch_config(current_config(runtime), capabilities)
    validation = validate_capabilities(config, capabilities)
    roles = config["roles"]
    return {
        "status": "current_preview",
        "runtime": runtime,
        "captured_at": now_utc(),
        "evidence": validation["evidence"],
        "roles": {
            "manager": roles["manager"],
            "worker": roles["worker"],
            "reviewer": roles["reviewer"],
        },
        "constraints": {
            "max_children": validation["effective_max_children"],
            "fast_mode": (
                config["constraints"]["fast_mode"]
                if runtime == "codex"
                else capabilities.get("fast_mode", "not_applicable")
            ),
        },
    }


def validate_capabilities(config: dict[str, Any], capabilities: dict[str, Any]) -> dict[str, Any]:
    runtime = config["runtime"]
    if capabilities.get("runtime") != runtime:
        raise ConfigError("host capability runtime does not match selected runtime")
    evidence = capabilities.get("evidence")
    _nonempty(evidence, "capabilities.evidence")
    for field in ("persistent_worker", "fresh_isolated_reviewers"):
        if capabilities.get(field) is not True:
            raise ConfigError(f"host must attest {field}=true")
    configured_max = config["constraints"].get("max_children")
    host_max = capabilities.get("max_children")
    _integer(host_max, "capabilities.max_children", 1)
    effective_max = min(configured_max, host_max) if configured_max else host_max

    if runtime == "codex":
        available = _mapping(capabilities.get("models"), "capabilities.models")
        for name, route in _route_pairs(config):
            model = route.get("model")
            reasoning = route.get("reasoning")
            if model is None:
                continue
            levels = available.get(model)
            if not isinstance(levels, list) or (
                reasoning is not None and reasoning not in levels
            ):
                raise ConfigError(
                    f"host cannot execute {name} route {model}/{reasoning}"
                )
        configured_fast = config["constraints"].get("fast_mode")
        if (
            configured_fast is not None
            and capabilities.get("fast_mode") is not configured_fast
        ):
            raise ConfigError(
                f"selected config requires fast_mode={str(configured_fast).lower()} on the host"
            )
    else:
        if capabilities.get("nested_delegation") is not True:
            raise ConfigError("Hermes workflow requires nested delegation")
        host_depth = capabilities.get("max_spawn_depth")
        _integer(host_depth, "capabilities.max_spawn_depth", 2)
        required_depth = config["constraints"].get("max_spawn_depth") or 2
        if host_depth < required_depth:
            raise ConfigError("host max_spawn_depth is below the selected requirement")
        configured_profiles = [
            (name, route)
            for name, route in _route_pairs(config)
            if route.get("profile") is not None
        ]
        if configured_profiles:
            profile_map = _mapping(
                capabilities.get("profiles"), "capabilities.profiles"
            )
            for name, route in configured_profiles:
                profile = route.get("profile")
                actual = profile_map.get(profile)
                if not isinstance(actual, dict):
                    raise ConfigError(f"host profile is unavailable for {name}: {profile}")
                if actual.get("provider") != route.get("provider") or actual.get("model") != route.get("model"):
                    raise ConfigError(f"host profile route does not match {name}: {profile}")
    return {
        "validated": True,
        "validated_at": now_utc(),
        "evidence": evidence.strip(),
        "effective_max_children": effective_max,
    }


def preflight(
    selection_path: str | Path | None,
    explicit_config_path: str | Path | None,
    override_path: str | Path | None,
    capabilities_path: str | Path,
) -> dict[str, Any]:
    resolved = resolve_selection(selection_path, explicit_config_path, override_path)
    if resolved["status"] != "resolved":
        return resolved
    capabilities = read_json(capabilities_path, "host capabilities")
    effective_config = resolve_dispatch_config(
        resolved["effective_config"], capabilities
    )
    host_validation = validate_capabilities(effective_config, capabilities)
    return {
        "snapshot_schema_version": SNAPSHOT_SCHEMA_VERSION,
        "status": "ready",
        "created_at": now_utc(),
        "runtime": resolved["runtime"],
        "policy_version": resolved["policy_version"],
        "effective_config": effective_config,
        "sources": resolved["sources"],
        "host_validation": host_validation,
    }


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    if snapshot.get("snapshot_schema_version") != SNAPSHOT_SCHEMA_VERSION:
        raise ConfigError(f"snapshot_schema_version must be {SNAPSHOT_SCHEMA_VERSION}")
    if snapshot.get("status") != "ready":
        raise ConfigError("runtime snapshot status must be ready")
    config = _mapping(snapshot.get("effective_config"), "effective_config")
    validate_config(config, snapshot.get("runtime"))
    if snapshot.get("policy_version") != config["policy"]["id"]:
        raise ConfigError("snapshot policy_version does not match effective_config")
    host = _mapping(snapshot.get("host_validation"), "host_validation")
    if host.get("validated") is not True:
        raise ConfigError("runtime snapshot requires successful host validation")
    _nonempty(host.get("evidence"), "host_validation.evidence")


def migrate_legacy(
    legacy_path: str | Path,
    runtime: str,
    base_config_path: str | Path | None,
) -> dict[str, Any]:
    legacy = read_json(legacy_path, "legacy models config")
    if runtime == "codex":
        base = (
            load_config(base_config_path, runtime)
            if base_config_path
            else current_config(runtime)
        )
    else:
        if base_config_path is None:
            raise ConfigError("Hermes migration requires --base-config with selected profiles")
        base = load_config(base_config_path, runtime)
    result = copy.deepcopy(base)
    result["selection_strategy"] = "custom"
    result["preset_id"] = None
    result["label"] = f"Migrated {runtime} role mapping"
    roles = result["roles"]
    allowed = {"_comment", "manager", "worker", "reviewer", "remote_worker"}
    unknown = set(legacy) - allowed
    if unknown:
        raise ConfigError(f"unknown legacy role keys: {', '.join(sorted(unknown))}")
    for role_name in ("manager", "worker", "reviewer", "remote_worker"):
        value = legacy.get(role_name)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ConfigError(f"legacy {role_name} must be a non-empty string or null")
    worker_value = legacy.get("worker")
    remote_value = legacy.get("remote_worker")
    if remote_value is not None and remote_value != worker_value:
        raise ConfigError(
            "legacy remote_worker must match worker; remote work reuses the implementation route"
        )

    def apply_model(route: dict[str, Any], model: str, field: str) -> None:
        if runtime == "hermes" and route.get("model") != model:
            raise ConfigError(
                f"cannot bind legacy {field}={model!r} to selected Hermes profile "
                "without compatible provider evidence"
            )
        route["model"] = model

    if legacy.get("manager") is not None:
        apply_model(roles["manager"], legacy["manager"], "manager")
    if worker_value is not None:
        for tier, route in roles["worker"]["tiers"].items():
            apply_model(route, worker_value, f"worker ({tier})")
    if legacy.get("reviewer") is not None:
        apply_model(roles["reviewer"], legacy["reviewer"], "reviewer")
    validate_config(result, runtime)
    result["legacy_migration"] = {
        "source": str(Path(legacy_path).resolve()),
        "migrated_at": now_utc(),
        "preserved_values": {
            name: legacy.get(name)
            for name in ("manager", "worker", "reviewer", "remote_worker")
        },
    }
    return result


def runtime_options(runtime: str | None = None) -> list[dict[str, Any]]:
    runtimes = (runtime,) if runtime else ("codex", "hermes")
    options: list[dict[str, Any]] = []
    for name in runtimes:
        options.append({
            "runtime": name,
            "strategy": "current",
            "details": (
                "Inspect with preview-current before saving; the saved "
                "model/reasoning/profile values inherit and each Issue preflight "
                "binds fresh concrete routes. "
                "If config/models.json contains mappings, run migrate-legacy, review the "
                "candidate, then select it as custom so those mappings are not discarded."
            ),
        })
        if name == "codex":
            preset = load_config(ROOT / "config" / "runtimes" / "codex.json", "codex")
            options.append({
                "runtime": name,
                "strategy": "tiered",
                "details": preset,
            })
        options.append({
            "runtime": name,
            "strategy": "custom",
            "details": "Supply a complete schema-v2 JSON config.",
        })
    return options


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    options = commands.add_parser("options", help="show concrete first-use choices")
    options.add_argument("--runtime", choices=("codex", "hermes"))

    preview = commands.add_parser(
        "preview-current", help="show inspected current settings without saving"
    )
    preview.add_argument("--runtime", choices=("codex", "hermes"), required=True)
    preview.add_argument("--capabilities", required=True)

    select = commands.add_parser("select", help="save an explicit user selection")
    select.add_argument("--selection", required=True)
    select.add_argument("--runtime", choices=("codex", "hermes"), required=True)
    select.add_argument("--strategy", choices=("current", "tiered", "custom"), required=True)
    select.add_argument("--config")
    select.add_argument("--capabilities")

    for name in ("resolve", "preflight"):
        command = commands.add_parser(name, help=f"{name} runtime selection")
        command.add_argument("--selection")
        command.add_argument("--config")
        command.add_argument("--override")
        command.add_argument("--output")
        if name == "preflight":
            command.add_argument("--capabilities", required=True)

    migrate = commands.add_parser(
        "migrate-legacy", help="create a candidate config from config/models.json"
    )
    migrate.add_argument("--legacy", required=True)
    migrate.add_argument("--runtime", choices=("codex", "hermes"), required=True)
    migrate.add_argument("--base-config")
    migrate.add_argument("--output")

    validate = commands.add_parser("validate", help="validate a runtime config")
    validate.add_argument("--config", required=True)
    validate.add_argument("--runtime", choices=("codex", "hermes"))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        if args.command == "options":
            result: dict[str, Any] | list[dict[str, Any]] = runtime_options(args.runtime)
        elif args.command == "preview-current":
            result = preview_current(args.runtime, args.capabilities)
        elif args.command == "select":
            result = select_runtime(
                args.selection,
                args.runtime,
                args.strategy,
                args.config,
                args.capabilities,
            )
        elif args.command == "resolve":
            result = resolve_selection(args.selection, args.config, args.override)
        elif args.command == "preflight":
            result = preflight(
                args.selection, args.config, args.override, args.capabilities
            )
        elif args.command == "migrate-legacy":
            result = migrate_legacy(args.legacy, args.runtime, args.base_config)
        else:
            result = load_config(args.config, args.runtime)
        output = getattr(args, "output", None)
        if output:
            if not isinstance(result, dict):
                raise ConfigError("--output requires an object result")
            write_json(output, result)
        else:
            json.dump(result, __import__("sys").stdout, ensure_ascii=False, indent=2, sort_keys=True)
            print()
    except ConfigError as exc:
        raise SystemExit(f"runtime configuration error: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
