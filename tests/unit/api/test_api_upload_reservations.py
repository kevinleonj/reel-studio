"""REVIEW-FIXES WEB 1: upload limits count sessions not yet finished."""

from reel_studio.core.config import load
from tests.unit.api.conftest import Api
from tests.unit.api.test_api_orders import new_order

LIMITS = load().limits.order


def batch(path: str, api: Api, auth: dict[str, str], files: list[dict[str, object]]) -> object:
    response = api.client.post(path, json={"files": files}, headers=auth)
    return response.status_code, response.json()


def test_a_second_full_batch_is_refused_before_any_file_finishes(api: Api) -> None:
    """Declared sizes are reserved at /uploads; finished files alone are not the limit."""
    order_id, auth = new_order(api)
    path = f"/api/orders/{order_id}/uploads"
    size = LIMITS.max_total_bytes // 2
    first = [{"name": f"a{i}.mp4", "size": size, "type": "video/mp4"} for i in range(2)]
    assert batch(path, api, auth, first)[0] == 200  # type: ignore[index]
    second = [{"name": "b.mp4", "size": size, "type": "video/mp4"}]
    assert batch(path, api, auth, second) == (413, {"error": "too_large"})


def test_files_are_counted_across_batches_before_they_finish(api: Api) -> None:
    order_id, auth = new_order(api)
    path = f"/api/orders/{order_id}/uploads"
    first = [{"name": f"{i}.mp4", "size": 1, "type": "video/mp4"} for i in range(LIMITS.max_files)]
    assert batch(path, api, auth, first)[0] == 200  # type: ignore[index]
    one_more = [{"name": "extra.mp4", "size": 1, "type": "video/mp4"}]
    assert batch(path, api, auth, one_more) == (413, {"error": "too_many_files"})


def test_asking_again_for_the_same_file_does_not_count_it_twice(api: Api) -> None:
    """A resumed or replaced upload asks for its name again (same name, last one wins: F310)."""
    order_id, auth = new_order(api)
    path = f"/api/orders/{order_id}/uploads"
    size = LIMITS.max_total_bytes // 2
    clip = [{"name": "Clip.MP4", "size": size, "type": "video/mp4"}]
    for _ in range(3):
        assert batch(path, api, auth, clip)[0] == 200  # type: ignore[index]
    again = [{"name": "clip.mp4", "size": size, "type": "video/mp4"}]
    assert batch(path, api, auth, again)[0] == 200  # type: ignore[index]
    other = [{"name": "other.mp4", "size": size, "type": "video/mp4"}]
    assert batch(path, api, auth, other)[0] == 200  # type: ignore[index]
