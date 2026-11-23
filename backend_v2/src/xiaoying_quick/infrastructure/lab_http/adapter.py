"""HTTPX adapter for the generate-only Quick Lab boundary."""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable, Mapping
from types import TracebackType

import httpx

from xiaoying_quick.modules.labs import (
    CandidateSQL,
    LabContractError,
    LabContractErrorCode,
    LabRequest,
    LabResponseExtractor,
)

from .config import LabHttpConfig
from .errors import LabHttpError, LabHttpErrorCode

_REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
_LOGGER = logging.getLogger(__name__)

#: Every ``features.*`` key the lab platform templates may reference.
_ALLOWED_FEATURE_KEYS = frozenset(
    {
        "cur_sales_year",
        "cur_sales_month",
        "max_sales_year",
        "max_sales_month",
        "trty_code",
        "kcode",
        "long_short_words",
        "columns_value_knowledge",
        "kpis",
        "Actual_Prompt",
        "golden_icl_list",
        "kpi_prompt",
        "que_prompt",
        "market_danwei",
        "remark",
        *(f"loop_prompt_{index}" for index in range(1, 6)),
    }
)
_FEATURE_VALUE_LIMIT = 4000


class HttpLabAdapter:
    """Call one configured Lab and release only extracted ``CandidateSQL``.

    The untrusted response body remains inside this adapter. HTTP errors are
    classified without reading their bodies, and neither causes nor response
    snippets are attached to the public exception.
    """

    # The documented endpoint accepts only the atomic question.  Keep this
    # explicit so orchestration never treats an ignored local prompt as repair.
    supports_controlled_prompt = False

    def __init__(
        self,
        config: LabHttpConfig,
        *,
        client: httpx.AsyncClient | None = None,
        extractor: LabResponseExtractor | None = None,
        request_id_factory: Callable[[], str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self._config = config
        self._client = client or httpx.AsyncClient(
            follow_redirects=False,
            trust_env=False,
        )
        self._owns_client = client is None
        self._extractor = extractor or LabResponseExtractor()
        self._request_id_factory = request_id_factory or (lambda: uuid.uuid4().hex)
        self._logger = logger or _LOGGER
        self._closed = False

    async def generate_sql(self, request: LabRequest) -> tuple[CandidateSQL, ...]:
        request_id = self._new_request_id()
        if self._closed:
            raise self._failure(
                LabHttpErrorCode.CLOSED,
                request_id=request_id,
                lab_id=request.lab_id,
                retryable=False,
            )

        invalid_request = False
        outbound: httpx.Request | None = None
        try:
            token = self._config.token_for(request.lab_id)
            features = _project_features(request.session_params)
            outbound = self._client.build_request(
                "POST",
                self._config.endpoint_url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {token}",
                    "X-Request-ID": request_id,
                },
                json={
                    "messages": [{"role": "user", "content": request.query}],
                    "stream": False,
                    "features": features,
                    "advanced_config": {},
                },
                timeout=self._config.timeout_seconds,
            )
        except (TypeError, ValueError, httpx.HTTPError):
            invalid_request = True
        if invalid_request or outbound is None:
            raise self._failure(
                LabHttpErrorCode.INVALID_REQUEST,
                request_id=request_id,
                lab_id=request.lab_id,
                retryable=False,
            )

        response: httpx.Response | None = None
        transport_failure: LabHttpErrorCode | None = None
        try:
            response = await self._client.send(
                outbound,
                stream=True,
                follow_redirects=False,
            )
        except httpx.TimeoutException:
            transport_failure = LabHttpErrorCode.TIMEOUT
        except Exception:
            transport_failure = LabHttpErrorCode.NETWORK_ERROR
        if transport_failure is not None or response is None:
            code = transport_failure or LabHttpErrorCode.NETWORK_ERROR
            raise self._failure(
                code,
                request_id=request_id,
                lab_id=request.lab_id,
                retryable=True,
            )

        status_failure = self._classify_status(response.status_code)
        if status_failure is not None:
            await _safe_close(response)
            code, retryable = status_failure
            raise self._failure(
                code,
                request_id=request_id,
                lab_id=request.lab_id,
                retryable=retryable,
                status_code=response.status_code,
            )

        content_length = _content_length(response)
        if content_length is not None and content_length > self._config.max_response_bytes:
            await _safe_close(response)
            raise self._failure(
                LabHttpErrorCode.RESPONSE_TOO_LARGE,
                request_id=request_id,
                lab_id=request.lab_id,
                retryable=False,
                status_code=response.status_code,
            )

        body = bytearray()
        read_failure: LabHttpErrorCode | None = None
        response_too_large = False
        try:
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > self._config.max_response_bytes:
                    response_too_large = True
                    break
                body.extend(chunk)
        except httpx.TimeoutException:
            read_failure = LabHttpErrorCode.TIMEOUT
        except Exception:
            read_failure = LabHttpErrorCode.NETWORK_ERROR
        finally:
            await _safe_close(response)

        if response_too_large:
            raise self._failure(
                LabHttpErrorCode.RESPONSE_TOO_LARGE,
                request_id=request_id,
                lab_id=request.lab_id,
                retryable=False,
                status_code=response.status_code,
            )
        if read_failure is not None:
            raise self._failure(
                read_failure,
                request_id=request_id,
                lab_id=request.lab_id,
                retryable=True,
                status_code=response.status_code,
            )

        raw_response: object | None = None
        invalid_json = False
        try:
            raw_response = json.loads(bytes(body))
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            invalid_json = True
        if invalid_json:
            raise self._failure(
                LabHttpErrorCode.INVALID_JSON,
                request_id=request_id,
                lab_id=request.lab_id,
                retryable=False,
                status_code=response.status_code,
            )

        candidates: tuple[CandidateSQL, ...] | None = None
        contract_code: LabContractErrorCode | None = None
        try:
            candidates = self._extractor.extract(
                _project_sql_citations(raw_response),
                atom_id=request.atom_id,
                lab_id=request.lab_id,
            )
        except LabContractError as error:
            contract_code = error.code
        if candidates is None:
            raise self._failure(
                LabHttpErrorCode.INVALID_RESPONSE,
                request_id=request_id,
                lab_id=request.lab_id,
                retryable=False,
                status_code=response.status_code,
                contract_code=contract_code,
            )

        self._logger.info(
            "Lab HTTP request completed",
            extra={
                "lab_request_id": request_id,
                "lab_identifier": request.lab_id,
                "http_status": response.status_code,
                "candidate_count": len(candidates),
            },
        )
        return candidates

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> HttpLabAdapter:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    def _new_request_id(self) -> str:
        request_id: object = None
        try:
            request_id = self._request_id_factory()
        except Exception:
            pass
        if isinstance(request_id, str) and _REQUEST_ID_PATTERN.fullmatch(request_id):
            return request_id
        return uuid.uuid4().hex

    @staticmethod
    def _classify_status(
        status_code: int,
    ) -> tuple[LabHttpErrorCode, bool] | None:
        if 200 <= status_code < 300:
            return None
        if status_code == 408:
            return LabHttpErrorCode.TIMEOUT, True
        if status_code == 429:
            return LabHttpErrorCode.RATE_LIMITED, True
        if 400 <= status_code < 500:
            return LabHttpErrorCode.HTTP_CLIENT_ERROR, False
        if 500 <= status_code < 600:
            return LabHttpErrorCode.HTTP_SERVER_ERROR, True
        return LabHttpErrorCode.UNEXPECTED_STATUS, False

    def _failure(
        self,
        code: LabHttpErrorCode,
        *,
        request_id: str,
        lab_id: str,
        retryable: bool,
        status_code: int | None = None,
        contract_code: LabContractErrorCode | None = None,
    ) -> LabHttpError:
        self._logger.warning(
            "Lab HTTP request failed",
            extra={
                "lab_request_id": request_id,
                "lab_identifier": lab_id,
                "lab_error_code": code.value,
                "http_status": status_code,
                "retryable": retryable,
                "contract_code": contract_code.value if contract_code else None,
            },
        )
        return LabHttpError(
            code,
            request_id=request_id,
            retryable=retryable,
            status_code=status_code,
            contract_code=contract_code,
        )


def _content_length(response: httpx.Response) -> int | None:
    value = response.headers.get("content-length")
    if value is None:
        return None
    try:
        length = int(value)
    except ValueError:
        return None
    return length if length >= 0 else None


async def _safe_close(response: httpx.Response) -> None:
    try:
        await response.aclose()
    except Exception:
        pass


def _project_features(session_params: Mapping[str, object]) -> dict[str, str]:
    """Project the documented feature parameters onto the outbound body.

    The lab templates reference ``features.*`` placeholders; only whitelisted
    keys are shipped, each as a bounded string. Time anchors travel as plain
    numbers because the templates render them like ``{{features.max_sales_month}}月``.
    """

    projected: dict[str, str] = {}
    for key, value in session_params.items():
        if key not in _ALLOWED_FEATURE_KEYS:
            continue
        if value is None:
            projected[key] = ""
            continue
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        projected[key] = value[:_FEATURE_VALUE_LIMIT]
    for index in range(1, 6):
        projected.setdefault(f"loop_prompt_{index}", "")
    return projected


def _project_sql_citations(response: object) -> object:
    """Keep nested SQL citations, the Lab's display narrative and its trace id."""

    if not isinstance(response, Mapping):
        return response
    message = response.get("message")
    if not isinstance(message, Mapping):
        return {}
    features = message.get("features")
    if not isinstance(features, Mapping) or "sql_citations" not in features:
        return {}
    content = message.get("content")
    narrative = content.strip()[:8_000] if isinstance(content, str) else ""
    projected: dict[str, object] = {"sql_citations": features["sql_citations"]}
    if narrative:
        projected["narrative"] = narrative
    # The Lab returns its own conversation/trace id at the top level; keep it
    # bounded so the UI can link back to the Lab run for source tracing.
    session_id = response.get("id")
    if isinstance(session_id, str) and session_id.strip():
        projected["lab_session_id"] = session_id.strip()[:128]
    return projected
