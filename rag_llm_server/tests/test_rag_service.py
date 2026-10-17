import asyncio
import inspect
from types import SimpleNamespace

import pytest

from services import rag_service as rag_module


def make_config(**overrides):
    values = {
        "VOLC_AK": "injected-ak",
        "VOLC_SK": "injected-secret",
        "KB_COLLECTION_NAME": "injected-collection",
        "KB_PROJECT_NAME": "injected-project",
        "VOLC_ACCOUNT_ID": "injected-account",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_constructor_uses_only_injected_rag_configuration():
    service = rag_module.RagService(make_config())

    assert service.ak == "injected-ak"
    assert service.sk == "injected-secret"
    assert service.collection_name == "injected-collection"
    assert service.project_name == "injected-project"
    assert service.account_id == "injected-account"


def test_service_source_has_no_legacy_collection_or_account_defaults():
    source = inspect.getsource(rag_module)

    assert "dw" + "_ai" not in source
    assert "kb-" + "2580e8a6357082fb" not in source
    assert "os." + "getenv" not in source


@pytest.mark.parametrize(
    "missing_field",
    [
        "VOLC_AK",
        "VOLC_SK",
        "KB_COLLECTION_NAME",
        "KB_PROJECT_NAME",
        "VOLC_ACCOUNT_ID",
    ],
)
def test_missing_configuration_returns_empty_without_leaking_values(
    capsys, missing_field, monkeypatch
):
    secret = "missing-secret-value"
    account = "missing-account-value"
    config = make_config(VOLC_SK=secret, VOLC_ACCOUNT_ID=account)
    setattr(config, missing_field, None)
    service = rag_module.RagService(config)
    monkeypatch.setattr(
        rag_module.httpx,
        "AsyncClient",
        lambda: pytest.fail("missing configuration must not reach upstream"),
    )

    result = asyncio.run(service.retrieve("question"))

    assert result == ""
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert account not in output.out + output.err


def test_upstream_failure_does_not_log_response_body(monkeypatch, capsys):
    secret_body = "upstream-secret-response"

    class Response:
        status_code = 500
        text = secret_body

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(rag_module.httpx, "AsyncClient", Client)
    service = rag_module.RagService(make_config())

    assert asyncio.run(service.retrieve("question")) == ""
    output = capsys.readouterr()
    assert secret_body not in output.out + output.err


def test_request_exception_does_not_log_exception_secret(monkeypatch, capsys):
    secret = "exception-secret-value"

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise RuntimeError(secret)

    monkeypatch.setattr(rag_module.httpx, "AsyncClient", Client)
    service = rag_module.RagService(make_config())

    assert asyncio.run(service.retrieve("question")) == ""
    output = capsys.readouterr()
    assert secret not in output.out + output.err


def test_success_keeps_joined_rag_context_without_printing_it(monkeypatch, capsys):
    contexts = ["first private context", "second private context"]

    class Response:
        status_code = 200

        def json(self):
            return {
                "data": {
                    "result_list": [{"content": value} for value in contexts]
                }
            }

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(rag_module.httpx, "AsyncClient", Client)
    service = rag_module.RagService(make_config())

    assert asyncio.run(service.retrieve("question")) == "\n\n".join(contexts)
    output = capsys.readouterr()
    assert contexts[0] not in output.out + output.err
    assert contexts[1] not in output.out + output.err


def test_upstream_uses_https_and_preserves_signing_request_semantics(monkeypatch):
    signed = []
    posted = []

    class SignerSpy:
        def __init__(self, request_data, service, region):
            signed.append((request_data, service, region))
            self.request_data = request_data

        def add_authorization(self, account):
            signed.append(account)
            self.request_data["headers"]["Authorization"] = "safe-signature"

    class Response:
        status_code = 200

        def json(self):
            return {"data": {"result_list": []}}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, **kwargs):
            posted.append((url, kwargs))
            return Response()

    monkeypatch.setattr(rag_module, "Signer", SignerSpy)
    monkeypatch.setattr(rag_module.httpx, "AsyncClient", Client)
    service = rag_module.RagService(make_config())

    assert asyncio.run(service.retrieve("question")) == ""

    request_data, signing_service, region = signed[0]
    assert request_data["method"] == "POST"
    assert request_data["path"] == "/api/knowledge/collection/search_knowledge"
    assert request_data["headers"]["Host"] == service.host
    assert request_data["headers"]["V-Account-Id"] == "injected-account"
    assert request_data["body"]["project"] == "injected-project"
    assert request_data["body"]["name"] == "injected-collection"
    assert signing_service == "air"
    assert region == "cn-north-1"
    assert signed[1] == {
        "accessKeyId": "injected-ak",
        "secretKey": "injected-secret",
    }
    url, kwargs = posted[0]
    assert url == (
        "https://api-knowledgebase.mlp.cn-beijing.volces.com"
        "/api/knowledge/collection/search_knowledge"
    )
    assert kwargs["headers"] is request_data["headers"]
    assert kwargs["json"] is request_data["body"]
