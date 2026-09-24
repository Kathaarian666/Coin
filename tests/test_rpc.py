import httpx
import pytest
import respx

from rhscanner.rpc import RpcClient, RpcError

URL = "https://rpc.test"


@respx.mock
async def test_retries_on_rate_limit(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    route = respx.post(URL).mock(side_effect=[
        httpx.Response(429), httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x10"}),
    ])
    rpc = RpcClient(URL, max_rps=0)
    assert await rpc.block_number() == 16
    assert route.call_count == 2
    await rpc.close()


@respx.mock
async def test_rpc_error_and_try_call():
    respx.post(URL).mock(return_value=httpx.Response(
        200, json={"jsonrpc": "2.0", "id": 1, "error": {"code": 3, "message": "execution reverted"}}
    ))
    rpc = RpcClient(URL, max_rps=0)
    with pytest.raises(RpcError):
        await rpc.call_fn("0x" + "1" * 40, "owner()", ["address"])
    assert await rpc.try_call_fn("0x" + "1" * 40, "owner()", ["address"]) is None
    await rpc.close()


async def _no_sleep(_):
    return None


@respx.mock
async def test_fails_over_to_backup_endpoint_and_returns_to_primary(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    primary = respx.post(URL).mock(return_value=httpx.Response(429))
    backup = respx.post("https://backup.test").mock(
        return_value=httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x20"})
    )
    rpc = RpcClient(URL, max_rps=0, fallback_urls=["https://backup.test"])
    assert await rpc.block_number() == 32
    assert primary.call_count == 1 and backup.call_count == 1
    assert await rpc.block_number() == 32  # stays on the backup for now
    assert primary.call_count == 1

    rpc._switched_at -= RpcClient.PRIMARY_RETRY_SECONDS + 1
    primary.mock(return_value=httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x10"}))
    assert await rpc.block_number() == 16
    await rpc.close()


@respx.mock
async def test_http_400_with_jsonrpc_error_is_an_rpc_error():
    route = respx.post(URL).mock(return_value=httpx.Response(
        400, json={"jsonrpc": "2.0", "id": 1, "error": {"code": 35, "message": "ranges over 10000 blocks"}}
    ))
    rpc = RpcClient(URL, max_rps=0)
    with pytest.raises(RpcError):
        await rpc.get_logs(0, 1, [])
    assert route.call_count == 1  # not retried: splitting the range is the caller's job
    await rpc.close()
