import json

import httpx
import pytest

from agent import Sender, make_batch
from collectors.docker import DockerCollector, client_for

RUNNING = "aaaaaaaaaaaa1111"
STOPPED = "bbbbbbbbbbbb2222"
IGNORED = "cccccccccccc3333"

LIST = [
    {"Id": RUNNING, "Names": ["/web"], "Image": "nginx:1.27", "State": "running", "Labels": {}},
    {"Id": STOPPED, "Names": ["/job"], "Image": "alpine", "State": "exited", "Labels": {}},
    {"Id": IGNORED, "Names": ["/tool"], "Image": "x", "State": "running", "Labels": {"vigil.ignore": "true"}},
]
STATS = {
    "cpu_stats": {"cpu_usage": {"total_usage": 300}, "system_cpu_usage": 2000},
    "precpu_stats": {"cpu_usage": {"total_usage": 100}, "system_cpu_usage": 1000},
    "memory_stats": {"usage": 600 * 1024 * 1024, "limit": 1000 * 1024 * 1024, "stats": {"inactive_file": 100 * 1024 * 1024}},
    "networks": {"eth0": {"rx_bytes": 1024, "tx_bytes": 2048}},
    "blkio_stats": {"io_service_bytes_recursive": [{"op": "Read", "value": 4096}, {"op": "Write", "value": 8192}]},
}


def docker_api(stats=STATS):
    def handler(req: httpx.Request):
        path = req.url.path
        if path == "/containers/json":
            return httpx.Response(200, json=LIST)
        cid = path.split("/")[2]
        if path.endswith("/json"):
            if cid == RUNNING[:12]:
                return httpx.Response(200, json={"RestartCount": 2, "State": {"Running": True, "OOMKilled": False, "Health": {"Status": "unhealthy"}}})
            return httpx.Response(200, json={"RestartCount": 0, "State": {"Running": False, "OOMKilled": True, "ExitCode": 137}})
        if path.endswith("/stats"):
            return httpx.Response(200, json=stats)
        return httpx.Response(404)
    return handler


def collector(handler=None):
    return DockerCollector(httpx.Client(transport=httpx.MockTransport(handler or docker_api()), base_url="http://docker"))


def by_metric(samples, cid):
    return {m: v for c, m, v in samples if c == cid}


def test_running_and_stopped_containers_are_described_and_measured():
    infos, samples = collector().collect()
    assert [i["name"] for i in infos] == ["web", "job"]  # vigil.ignore=true пропущено
    web = by_metric(samples, RUNNING[:12])
    assert web["container_running"] == 1 and web["container_restarts"] == 2 and web["container_health"] == 0
    assert web["container_cpu"] == pytest.approx(20.0)  # 200 / 1000 приросту
    assert web["container_mem"] == pytest.approx(50.0) and web["container_mem_bytes"] == pytest.approx(500.0)  # без кешу
    job = by_metric(samples, STOPPED[:12])
    assert job["container_running"] == 0 and job["container_oom_killed"] == 1 and job["container_exit_code"] == 137
    assert "container_cpu" not in job


def test_network_and_disk_rates_appear_from_the_second_cycle():
    c = collector()
    _, first = c.collect()
    assert "container_net_in" not in by_metric(first, RUNNING[:12])
    _, second = c.collect()
    web = by_metric(second, RUNNING[:12])
    assert {"container_net_in", "container_net_out", "container_block_read", "container_block_write"} <= web.keys()


def test_name_masks_are_ignored():
    infos, _ = DockerCollector(httpx.Client(transport=httpx.MockTransport(docker_api()), base_url="http://docker"), ["jo*"]).collect()
    assert [i["name"] for i in infos] == ["web"]


def test_broken_container_does_not_break_the_others():
    def handler(req):
        if req.url.path.endswith("/stats"):
            return httpx.Response(500)
        return docker_api()(req)
    infos, samples = collector(handler).collect()
    assert [i["name"] for i in infos] == ["job"]  # web не вдалося прочитати, job – вдалося
    assert by_metric(samples, STOPPED[:12])["container_running"] == 0


def test_docker_url_schemes():
    assert client_for("tcp://127.0.0.1:2375").base_url == "http://127.0.0.1:2375"
    with pytest.raises(ValueError):
        client_for("npipe:////./pipe/docker_engine")


def test_sender_posts_object_with_containers_and_plain_list_without():
    bodies = []
    s = Sender(httpx.Client(transport=httpx.MockTransport(lambda r: bodies.append(json.loads(r.read())) or httpx.Response(200, json={}))),
               "https://x.test", "vgl_t")
    batch = make_batch("web-01", [("cpu_usage", "", 5.0)], [("aaa", "container_cpu", 1.5)])
    assert batch[1]["target"] == "docker:aaa" and batch[1]["metric"] == "container_cpu"
    s.send(batch, {"containers": [{"id": "aaa", "name": "web", "image": "nginx", "state": "running"}]})
    assert bodies[0]["containers"][0]["name"] == "web" and len(bodies[0]["records"]) == 2
    s.send(batch)  # без Docker – старий формат (список)
    assert isinstance(bodies[1], list)
