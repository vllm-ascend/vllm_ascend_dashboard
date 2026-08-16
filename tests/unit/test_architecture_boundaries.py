"""Import-boundary checks for the independently deployable backend roles."""
from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2] / "backend"


def _imports_under(package: str) -> set[str]:
    imports: set[str] = set()
    for source in (BACKEND / package).rglob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


def _assert_no_role_imports(package: str, forbidden: tuple[str, ...]) -> None:
    violations = sorted(
        imported
        for imported in _imports_under(package)
        if imported == forbidden or imported.startswith(tuple(f"{name}." for name in forbidden))
    )
    assert not violations, f"{package} has forbidden role imports: {violations}"


def test_legacy_shared_package_is_removed() -> None:
    assert not (BACKEND / "shared").exists(), "business code must not return to backend/shared"


def test_api_has_no_mixed_business_services_bucket() -> None:
    assert not (BACKEND / "api" / "services").exists(), (
        "domain services must live in their owning package, not backend/api/services"
    )


def test_resource_dashboard_services_are_not_in_infrastructure_clients() -> None:
    clients = BACKEND / "infrastructure" / "clients"
    assert not (clients / "resource_dashboard.py").exists(), (
        "resource dashboard business logic must live in backend/resource_dashboard"
    )
    assert not (clients / "resource_metrics_query.py").exists(), (
        "resource dashboard read models must not live in infrastructure/clients"
    )
    assert (BACKEND / "resource_dashboard" / "service.py").exists()
    assert (BACKEND / "resource_dashboard" / "metrics_query.py").exists()


def test_clients_directory_contains_only_external_adapters() -> None:
    clients = BACKEND / "infrastructure" / "clients"
    assert not (clients / "litellm_sync.py").exists(), (
        "LiteLLM synchronization belongs to the model_sync domain"
    )
    assert not (clients / "rate_limiter.py").exists(), (
        "rate limiting belongs to infrastructure security, not external clients"
    )
    assert (BACKEND / "model_sync" / "litellm_sync.py").exists()
    assert (BACKEND / "infrastructure" / "core" / "rate_limiter.py").exists()


def test_scheduler_never_depends_on_the_http_api() -> None:
    _assert_no_role_imports("scheduler", ("api",))


def test_scheduler_never_depends_on_collector_implementation() -> None:
    _assert_no_role_imports("scheduler", ("collector",))


def test_api_never_depends_on_collector_implementation() -> None:
    _assert_no_role_imports("api", ("collector",))


def test_reporting_never_depends_on_http_api() -> None:
    _assert_no_role_imports("reporting", ("api",))


def test_collector_has_no_generic_services_bucket() -> None:
    assert not (BACKEND / "collector" / "services").exists()
