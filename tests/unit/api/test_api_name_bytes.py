"""REVIEW-FIXES WEB 4: file names are limited in UTF-8 bytes, as the disk counts them."""

from reel_studio.core.constants import FILE_NAME_MAX_BYTES
from tests.unit.api.conftest import Api
from tests.unit.api.test_api_orders import new_order


def batch(path: str, api: Api, auth: dict[str, str], files: list[dict[str, object]]) -> object:
    response = api.client.post(path, json={"files": files}, headers=auth)
    return response.status_code, response.json()


E_ACUTE = "é"  # two bytes in UTF-8


def test_a_name_over_255_bytes_is_refused_with_its_message(api: Api) -> None:
    order_id, auth = new_order(api)
    path = f"/api/orders/{order_id}/uploads"
    name = E_ACUTE * 204 + ".mp4"  # 208 characters, 412 bytes: passed the old character limit
    files = [{"name": name, "size": 1, "type": "video/mp4"}]
    assert batch(path, api, auth, files) == (400, {"error": "name_too_long", "file": name})


def test_a_name_of_exactly_255_bytes_is_accepted(api: Api) -> None:
    order_id, auth = new_order(api)
    path = f"/api/orders/{order_id}/uploads"
    name = E_ACUTE * 125 + "a.mp4"  # 250 + 5 bytes
    assert len(name.encode()) == FILE_NAME_MAX_BYTES
    files = [{"name": name, "size": 1, "type": "video/mp4"}]
    assert batch(path, api, auth, files)[0] == 200  # type: ignore[index]
    longer = [{"name": E_ACUTE + name, "size": 1, "type": "video/mp4"}]
    assert batch(path, api, auth, longer)[0] == 400  # type: ignore[index]
