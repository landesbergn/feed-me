import os
from dataclasses import dataclass, field

import pytest

os.environ.setdefault("OPENAI_API_KEY", "sk-test-dummy")


@dataclass
class FakeResponse:
    status_code: int = 200
    text: str = ""
    content: bytes = b""

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@dataclass
class FakeHttp:
    """Replaces httpx.Client. Returns FakeResponse for any URL."""
    responses: dict[str, FakeResponse] = field(default_factory=dict)
    default: FakeResponse = field(default_factory=FakeResponse)

    def get(self, url, **kwargs):
        return self.responses.get(url, self.default)


@dataclass
class FakeTTSResponse:
    content: bytes


@dataclass
class FakeOpenAI:
    """Replaces the openai client object for ingest tests."""
    audio_bytes: bytes = b"FAKEMP3"
    calls: list[dict] = field(default_factory=list)

    class _Audio:
        def __init__(self, parent):
            self.parent = parent

        @property
        def speech(self):
            return self

        def create(self, **kwargs):
            self.parent.calls.append(kwargs)
            return FakeTTSResponse(content=self.parent.audio_bytes)

    @property
    def audio(self):
        return self._Audio(self)


@pytest.fixture
def fake_http():
    return FakeHttp()


@pytest.fixture
def fake_openai():
    return FakeOpenAI()
