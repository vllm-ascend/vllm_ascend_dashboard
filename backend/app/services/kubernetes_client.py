import base64
import hashlib
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet
from kubernetes_asyncio import client, config
from kubernetes_asyncio.client import ApiClient, CoreV1Api, CustomObjectsApi

from app.core.config import settings
from app.models import KubernetesClusterConfig


def _fernet() -> Fernet:
    secret = settings.KUBECONFIG_ENCRYPTION_KEY or settings.JWT_SECRET
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_kubeconfig(kubeconfig: str) -> str:
    return _fernet().encrypt(kubeconfig.encode("utf-8")).decode("utf-8")


def decrypt_kubeconfig(kubeconfig_encrypted: str) -> str:
    return _fernet().decrypt(kubeconfig_encrypted.encode("utf-8")).decode("utf-8")


class KubernetesClientFactory:
    async def create_api_client(self, cluster: KubernetesClusterConfig) -> ApiClient:
        kubeconfig = decrypt_kubeconfig(cluster.kubeconfig_encrypted)
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as temp_file:
            temp_file.write(kubeconfig)
            temp_path = temp_file.name

        try:
            configuration = client.Configuration()
            await config.load_kube_config(
                config_file=temp_path,
                context=cluster.context,
                client_configuration=configuration,
            )
            return ApiClient(configuration=configuration)
        finally:
            Path(temp_path).unlink(missing_ok=True)


async def list_nodes(api_client: ApiClient):
    api = CoreV1Api(api_client)
    response = await api.list_node(_request_timeout=30)
    return response.items


async def list_pods(api_client: ApiClient, namespaces: list[str] | None, label_selector: str | None):
    api = CoreV1Api(api_client)
    if namespaces:
        pods = []
        for namespace in namespaces:
            response = await api.list_namespaced_pod(namespace=namespace, label_selector=label_selector, _request_timeout=30)
            pods.extend(response.items)
        return pods

    response = await api.list_pod_for_all_namespaces(label_selector=label_selector, _request_timeout=30)
    return response.items


async def list_ephemeral_runners(api_client: ApiClient, namespace: str):
    api = CustomObjectsApi(api_client)
    response = await api.list_namespaced_custom_object(
        group="actions.github.com",
        version="v1alpha1",
        namespace=namespace,
        plural="ephemeralrunners",
        _request_timeout=30,
    )
    return response.get("items", [])
