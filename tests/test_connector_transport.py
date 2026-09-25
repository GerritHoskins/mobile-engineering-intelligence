"""Record/replay transport and scrubbing, without network."""

import httpx

from app.connectors.http import RecordingTransport, ReplayTransport, SCRUBBED, iter_link_pages, scrub


def test_scrub_removes_identifying_fields_recursively() -> None:
    payload = {"fields": {"reporter": {"emailAddress": "a@b.c", "accountId": "123", "displayName": "A"},
                          "summary": "keep me"}, "self": "https://x/rest/api/3/issue/1"}
    assert scrub(payload) == {"fields": {"reporter": {"emailAddress": SCRUBBED, "accountId": SCRUBBED,
                                                      "displayName": SCRUBBED}, "summary": "keep me"},
                              "self": SCRUBBED}


def test_record_then_replay_round_trip_with_link_pagination(tmp_path) -> None:
    pages = {
        None: ([1, 2], '<https://api.example/items?cursor=b>; rel="next"; results="true"; cursor="b"'),
        "b": ([3], '<https://api.example/items?cursor=c>; rel="next"; results="false"; cursor="c"'),
    }

    def upstream(request: httpx.Request) -> httpx.Response:
        body, link = pages[request.url.params.get("cursor")]
        return httpx.Response(200, json=body, headers={"link": link, "content-type": "application/json"})

    def collect(transport) -> list[int]:
        client = httpx.Client(base_url="https://api.example", transport=transport)
        return [item for page in iter_link_pages(client, "/items") for item in page.json()]

    assert collect(RecordingTransport(tmp_path, httpx.MockTransport(upstream))) == [1, 2, 3]
    assert collect(ReplayTransport(tmp_path)) == [1, 2, 3]  # results="false" stops pagination


def test_replay_fails_loudly_for_unrecorded_request(tmp_path) -> None:
    client = httpx.Client(base_url="https://api.example", transport=ReplayTransport(tmp_path))
    try:
        client.get("/never-recorded")
    except FileNotFoundError as error:
        assert "No recorded fixture" in str(error)
    else:
        raise AssertionError("expected FileNotFoundError")
