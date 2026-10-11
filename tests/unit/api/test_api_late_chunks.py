"""REVIEW-FIXES WEB 2: no chunk is stored once the order has started."""

from tests.unit.api.conftest import Api
from tests.unit.api.test_api_orders import new_order, upload


def test_chunks_are_refused_once_the_order_has_started(api: Api) -> None:
    order_id, auth = new_order(api)
    upload(api, order_id, auth)  # one finished file, so Start is allowed
    files = [{"name": "late.mp4", "size": 4, "type": "video/mp4"}]
    [target] = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": files}, headers=auth
    ).json()["targets"]
    assert api.client.post(f"/api/orders/{order_id}/start", headers=auth).status_code == 200
    late = api.client.put(
        target["upload_url"], content=b"0123", headers={"Content-Range": "bytes 0-3/4"}
    )
    assert (late.status_code, late.json()) == (409, {"error": "wrong_status"})
    assert [f["name"] for f in api.storage.list_inputs(order_id)] == ["a.mp4"]


def test_a_status_query_is_refused_too_once_started(api: Api) -> None:
    order_id, auth = new_order(api)
    files = [{"name": "a.mp4", "size": 4, "type": "video/mp4"}]
    [target] = api.client.post(
        f"/api/orders/{order_id}/uploads", json={"files": files}, headers=auth
    ).json()["targets"]
    api.client.put(target["upload_url"], content=b"0123", headers={"Content-Range": "bytes 0-3/4"})
    api.client.post(f"/api/orders/{order_id}/start", headers=auth)
    query = api.client.put(target["upload_url"], headers={"Content-Range": "bytes */4"})
    assert query.status_code == 409
