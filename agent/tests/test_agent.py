import httpx

from agent import MAX_BUFFERED, Sender, make_batch
from collectors.system import SystemCollector

PERCENT = {"cpu_usage", "ram_usage", "swap_usage", "disk_usage"}


def test_collector_returns_known_valid_metrics():
    c = SystemCollector()
    samples = c.collect()
    names = {m for m, _, _ in samples}
    assert {"cpu_usage", "ram_usage", "swap_usage", "process_count", "cpu_cores", "net_total", "disk_usage"} <= names
    for metric, _, value in samples:
        assert value >= 0, metric
        if metric in PERCENT:
            assert value <= 100, metric


def test_disk_filter_keeps_only_listed():
    disks = [i for m, i, _ in SystemCollector().collect() if m == "disk_usage"]
    assert disks
    only = SystemCollector([disks[0]]).collect()
    assert {i for m, i, _ in only if m == "disk_usage"} == {disks[0]}


def _sender(handler):
    return Sender(httpx.Client(transport=httpx.MockTransport(handler)), "https://x.test", "vgl_t")


def test_batch_has_host_and_timestamp():
    b = make_batch("web-01", [("cpu_usage", "", 5.0)])
    assert b[0]["host"] == "web-01" and b[0]["timestamp"] and b[0]["metric"] == "cpu_usage"


def test_buffer_is_flushed_in_order_in_one_request_when_connection_returns():
    import json
    online, got = [False], []

    def handler(req: httpx.Request):
        if not online[0]:
            raise httpx.ConnectError("offline")
        got.append(json.loads(req.read()))
        return httpx.Response(200, json={"accepted": 1, "rejected": []})

    s = _sender(handler)
    assert s.send([{"n": 1}]) is None and s.send([{"n": 2}]) is None
    assert len(s.queue) == 2
    online[0] = True
    assert s.send([{"n": 3}]) == 200
    assert got == [[{"n": 1}, {"n": 2}, {"n": 3}]] and not s.queue


def test_backlog_is_sent_in_chunks_of_at_most_500_records():
    import json
    online, sizes = [False], []

    def handler(req: httpx.Request):
        if not online[0]:
            raise httpx.ConnectError("offline")
        sizes.append(len(json.loads(req.read())))
        return httpx.Response(200, json={})

    s = _sender(handler)
    for _ in range(60):
        s.send([{"n": 0}] * 20)  # 1200 записів у буфері
    online[0] = True
    while s.queue:
        s.send([{"n": 0}] * 20)
    assert max(sizes) <= 500 and len(sizes) > 2


def test_interval_header_is_sent():
    seen = []
    s = Sender(httpx.Client(transport=httpx.MockTransport(lambda r: seen.append(r.headers) or httpx.Response(200, json={}))),
               "https://x.test", "vgl_t", 60)
    s.send([{"n": 1}])
    assert seen[0]["x-agent-interval"] == "60"


def test_buffer_is_capped():
    s = _sender(lambda r: (_ for _ in ()).throw(httpx.ConnectError("offline")))
    for i in range(MAX_BUFFERED + 20):
        s.send([{"n": i}])
    assert len(s.queue) == MAX_BUFFERED


def test_unauthorized_is_reported_and_keeps_batch():
    s = _sender(lambda r: httpx.Response(401, json={}))
    assert s.send([{"n": 1}]) == 401 and len(s.queue) == 1


def test_bad_batch_is_dropped_not_retried_forever():
    s = _sender(lambda r: httpx.Response(422, json={}))
    s.send([{"n": 1}])
    assert not s.queue
