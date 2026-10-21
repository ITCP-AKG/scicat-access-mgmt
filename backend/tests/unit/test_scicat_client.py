"""The real SciCat REST client against a mocked SciCat (respx): service-account auth,
URL encoding, the v4 `limits` filter shape, paging and error mapping."""

import json

import httpx
import pytest
import respx

from app.services.scicat_client import (
    ScicatAuthError,
    ScicatClient,
    ScicatError,
    ScicatUnavailable,
    resource_id,
)

BASE = "http://scicat/api/v3"


def _client(**kw) -> ScicatClient:
    return ScicatClient(BASE, username="svc", password="pw", **kw)


def _login_route(router, token="svc-token", expires_in=3600):
    return router.post(f"{BASE}/auth/login").mock(
        return_value=httpx.Response(201, json={"access_token": token, "expires_in": expires_in})
    )


@pytest.mark.asyncio
async def test_patch_url_encodes_pid_and_sends_service_token():
    with respx.mock(assert_all_called=True) as router:
        login = _login_route(router)
        patch = router.patch(f"{BASE}/datasets/PID.CATORGA.PREFIX%2Fabc-1").mock(
            return_value=httpx.Response(200, json={"pid": "PID.CATORGA.PREFIX/abc-1"})
        )
        client = _client()
        await client.patch_resource("dataset", "PID.CATORGA.PREFIX/abc-1", {"accessGroups": ["g"]})
        await client.patch_resource("dataset", "PID.CATORGA.PREFIX/abc-1", {"accessGroups": ["g"]})
        await client.aclose()

    assert login.call_count == 1  # token cached between calls
    req = patch.calls.last.request
    assert req.headers["Authorization"] == "Bearer svc-token"
    assert json.loads(req.content) == {"accessGroups": ["g"]}


@pytest.mark.asyncio
async def test_list_uses_limits_filter_and_per_type_param_name():
    with respx.mock() as router:
        _login_route(router)
        datasets = router.get(f"{BASE}/datasets").mock(return_value=httpx.Response(200, json=[]))
        proposals = router.get(f"{BASE}/proposals").mock(return_value=httpx.Response(200, json=[]))
        client = _client()
        await client.list_resources("dataset", {"ownerGroup": "g"}, limit=20, skip=40)
        await client.list_resources("proposal", None, limit=5)
        await client.aclose()

    ds_filter = json.loads(datasets.calls.last.request.url.params["filter"])
    assert ds_filter == {"where": {"ownerGroup": "g"}, "limits": {"limit": 20, "skip": 40}}
    # the proposals controller reads `filters`, not `filter`
    assert "filters" in proposals.calls.last.request.url.params


@pytest.mark.asyncio
async def test_iter_resources_pages_until_short_page():
    pages = [[{"pid": f"p{i}"} for i in range(100)], [{"pid": "last"}]]

    def respond(request):
        skip = json.loads(request.url.params["filter"])["limits"]["skip"]
        return httpx.Response(200, json=pages[skip // 100])

    with respx.mock() as router:
        _login_route(router)
        router.get(f"{BASE}/datasets").mock(side_effect=respond)
        client = _client()
        docs = [d async for d in client.iter_resources("dataset", {"ownerEmail": "a@b"})]
        await client.aclose()
    assert len(docs) == 101 and docs[-1]["pid"] == "last"


@pytest.mark.asyncio
async def test_relogin_once_on_401():
    with respx.mock() as router:
        login = router.post(f"{BASE}/auth/login").mock(
            side_effect=[
                httpx.Response(201, json={"access_token": "old", "expires_in": 3600}),
                httpx.Response(201, json={"access_token": "new", "expires_in": 3600}),
            ]
        )
        get = router.get(f"{BASE}/samples/s1").mock(
            side_effect=[httpx.Response(401), httpx.Response(200, json={"sampleId": "s1"})]
        )
        client = _client()
        doc = await client.get_resource("sample", "s1")
        await client.aclose()
    assert doc["sampleId"] == "s1"
    assert login.call_count == 2
    assert get.calls.last.request.headers["Authorization"] == "Bearer new"


@pytest.mark.asyncio
async def test_error_mapping():
    with respx.mock() as router:
        _login_route(router)
        router.get(f"{BASE}/auth/whoami").mock(return_value=httpx.Response(401))
        router.get(f"{BASE}/samples/down").mock(return_value=httpx.Response(503))
        router.get(f"{BASE}/samples/gone").mock(return_value=httpx.Response(404))
        router.get(f"{BASE}/samples/net").mock(side_effect=httpx.ConnectError("refused"))
        client = _client()
        with pytest.raises(ScicatAuthError):
            await client.whoami("bad")
        with pytest.raises(ScicatUnavailable):
            await client.get_resource("sample", "down")
        with pytest.raises(ScicatError) as gone:
            await client.get_resource("sample", "gone")
        assert gone.value.status == 404 and not isinstance(gone.value, ScicatUnavailable)
        with pytest.raises(ScicatUnavailable):
            await client.get_resource("sample", "net")
        await client.aclose()


@pytest.mark.asyncio
async def test_static_token_skips_login():
    with respx.mock(assert_all_called=False) as router:
        login = _login_route(router)
        get = router.get(f"{BASE}/proposals/P1").mock(
            return_value=httpx.Response(200, json={"proposalId": "P1"})
        )
        client = ScicatClient(BASE, token="static")
        await client.get_resource("proposal", "P1")
        await client.aclose()
    assert login.call_count == 0
    assert get.calls.last.request.headers["Authorization"] == "Bearer static"


def test_resource_id_helper():
    assert resource_id("dataset", {"pid": "a/b"}) == "a/b"
    assert resource_id("origdatablock", {"_id": "o1"}) == "o1"
    assert resource_id("origdatablock", {"id": "o2"}) == "o2"
    assert resource_id("sample", {}) == ""
