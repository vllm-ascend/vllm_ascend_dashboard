from types import SimpleNamespace

from cryptography.fernet import InvalidToken
import pytest

from resource_dashboard.service import ResourceDashboardService


@pytest.mark.asyncio
async def test_empty_exception_message_is_not_persisted_as_success() -> None:
    service = ResourceDashboardService()

    async def raise_invalid_token(*_args, **_kwargs):
        raise InvalidToken

    service.build_cluster_summary = raise_invalid_token  # type: ignore[method-assign]
    cluster = SimpleNamespace(
        id=1,
        name="dev-a2",
        namespaces="vllm-project",
        default_label_selector=None,
    )

    summary, _, _ = await service._safe_build_cluster_summary(cluster, None, False)

    assert summary.error == "InvalidToken"
