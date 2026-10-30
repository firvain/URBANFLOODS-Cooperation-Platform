import uuid


async def test_request_id_header_added(client):
    generated = await client.get("/health")
    assert "x-request-id" in generated.headers
    uuid.UUID(generated.headers["x-request-id"])  # a generated id is a UUID

    sent = "3f2b8c1e-test-request-id"
    echoed = await client.get("/health", headers={"X-Request-ID": sent})
    assert echoed.headers["x-request-id"] == sent

    missing = await client.get("/does-not-exist")
    assert missing.status_code == 404
    assert "x-request-id" in missing.headers
