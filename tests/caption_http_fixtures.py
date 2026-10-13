"""Synthetic responses served through requests' public HTTPAdapter boundary."""

import json
from pathlib import Path

try:
    import requests
except ImportError:
    requests = None

VIDEO = "fixture0001"
FIXTURES = Path(__file__).parent / "fixtures" / "captions"


def caption_fixture(name):
    return (FIXTURES / name).read_bytes()


def caption_url(name):
    return f"https://www.youtube.com/api/timedtext?fixture={name}"


def listing_script(specs=(), *, player=None):
    if player is None:
        tracks = []
        for name, language, generated in specs:
            entry = {"baseUrl": caption_url(name), "languageCode": language,
                     "name": {"runs": [{"text": "Synthetic caption track"}]}}
            if generated:
                entry["kind"] = "asr"
            tracks.append(entry)
        player = {"playabilityStatus": {"status": "OK"}, "captions": {
            "playerCaptionsTracklistRenderer": {"captionTracks": tracks}}}
    return [("GET", "/watch?v=", '<html>"INNERTUBE_API_KEY": "synthetic-key"</html>', 200),
            ("POST", "/youtubei/v1/player?", player, 200)]


class SyntheticHTTPAdapter(requests.adapters.HTTPAdapter if requests else object):
    """No fallback to a live transport: every request must match the next fixture."""

    def __init__(self, script):
        super().__init__()
        self.script = list(script)
        self.calls = []
        self.closed = False

    def send(self, request, **kwargs):
        self.calls.append((request.method, request.url, dict(kwargs), request.body))
        if not self.script:
            raise AssertionError("Unexpected request; live network is disabled")
        method, url_part, payload, status = self.script.pop(0)
        if request.method != method or url_part not in request.url:
            raise AssertionError("Request does not match its synthetic fixture")
        if isinstance(payload, Exception):
            raise payload
        response = requests.Response()
        response.status_code = status
        response.url = request.url
        response.request = request
        response.encoding = "utf-8"
        response.headers["Content-Type"] = "application/xml; charset=utf-8"
        if isinstance(payload, dict):
            payload = json.dumps(payload).encode("utf-8")
            response.headers["Content-Type"] = "application/json; charset=utf-8"
        response._content = payload.encode("utf-8") if isinstance(payload, str) else payload
        return response

    def close(self):
        self.closed = True
        super().close()
