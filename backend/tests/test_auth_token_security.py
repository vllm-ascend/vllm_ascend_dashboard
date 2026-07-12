from app.core.security import create_access_token, create_refresh_token, decode_token


def test_access_and_refresh_tokens_have_distinct_types():
    identity = {"sub": "alice", "user_id": 1, "role": "user"}

    access_payload = decode_token(create_access_token(identity))
    refresh_payload = decode_token(create_refresh_token(identity))

    assert access_payload is not None
    assert refresh_payload is not None
    assert access_payload["token_type"] == "access"
    assert refresh_payload["token_type"] == "refresh"
    assert access_payload["jti"] != refresh_payload["jti"]
