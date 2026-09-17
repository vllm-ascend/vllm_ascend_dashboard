from infrastructure.clients.llm_client import OpenAIClient, create_client


def test_create_client_supports_deepseek_openai_compatible_api():
    client = create_client(
        provider="deepseek",
        api_key="test-key",
        api_base="https://api.deepseek.com/v1",
    )

    assert isinstance(client, OpenAIClient)
    assert client.api_key == "test-key"
    assert client.api_base == "https://api.deepseek.com/v1"
