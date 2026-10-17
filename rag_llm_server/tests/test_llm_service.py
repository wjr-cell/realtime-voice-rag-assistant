from concurrent.futures import ThreadPoolExecutor
import threading
from types import SimpleNamespace

from config import Config
from services import llm_service as llm_module


def test_constructor_is_lazy_and_does_not_require_an_api_key(monkeypatch):
    calls = []

    def ark_spy(**kwargs):
        calls.append(kwargs)
        raise AssertionError("Ark must not be constructed eagerly")

    monkeypatch.setattr(llm_module, "Ark", ark_spy)

    service = llm_module.LLMService(Config({}))

    assert service.client is None
    assert calls == []


def test_first_chat_stream_constructs_and_caches_ark(monkeypatch):
    calls = []
    create_calls = []
    chunks = [object(), object()]

    class FakeCompletions:
        def create(self, **kwargs):
            create_calls.append(kwargs)
            return iter(chunks)

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=FakeCompletions())
    )

    def ark_spy(**kwargs):
        calls.append(kwargs)
        return fake_client

    monkeypatch.setattr(llm_module, "Ark", ark_spy)
    config = Config(
        {"ARK_API_KEY": "test-key", "ARK_ENDPOINT_ID": "endpoint-id"}
    )
    service = llm_module.LLMService(config)
    history = [{"role": "user", "content": "hello"}]

    assert list(service.chat_stream(history, "reference")) == chunks
    assert list(service.chat_stream(history)) == chunks

    assert calls == [
        {
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "api_key": "test-key",
            "timeout": 1800,
        }
    ]
    assert service.client is fake_client
    assert len(create_calls) == 2
    first_call = create_calls[0]
    assert first_call["model"] == "endpoint-id"
    assert first_call["temperature"] == 0.3
    assert first_call["stream"] is True
    assert first_call["stream_options"] == {"include_usage": True}
    assert first_call["messages"][0]["role"] == "system"
    assert "reference" in first_call["messages"][0]["content"]
    assert first_call["messages"][1:] == history


def test_chat_stream_failure_yields_none_without_leaking_secrets(
    monkeypatch, capsys
):
    secret = "super-secret-api-key"

    def failing_ark(**kwargs):
        raise RuntimeError(f"request rejected for {secret}")

    monkeypatch.setattr(llm_module, "Ark", failing_ark)
    service = llm_module.LLMService(
        Config({"ARK_API_KEY": secret, "ARK_ENDPOINT_ID": "endpoint-id"})
    )

    assert list(service.chat_stream([{"role": "user", "content": "hello"}])) == [
        None
    ]
    assert secret not in capsys.readouterr().out


def test_concurrent_first_access_constructs_one_shared_client(monkeypatch):
    start_barrier = threading.Barrier(2)
    constructor_barrier = threading.Barrier(2)
    clients = []

    def ark_spy(**kwargs):
        client = object()
        clients.append(client)
        try:
            constructor_barrier.wait(timeout=0.5)
        except threading.BrokenBarrierError:
            pass
        return client

    monkeypatch.setattr(llm_module, "Ark", ark_spy)
    service = llm_module.LLMService(Config({"ARK_API_KEY": "test-key"}))

    def get_client_together():
        start_barrier.wait(timeout=1)
        return service._get_client()

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: get_client_together(), range(2)))

    assert len(clients) == 1
    assert results[0] is results[1] is clients[0]
