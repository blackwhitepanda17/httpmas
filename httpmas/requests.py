"""
RequestManager - Quản lý và điều phối toàn bộ HTTP request đồng bộ.
Nâng cấp:
Accept-Encoding: gzip, deflate.
Tự giải nén body.
Dùng parser trả should_close.
Request builder cache header prefix.
Request-level retry cho stale pooled connections.
"""

import socket
import time
import json as _json
import gzip
import zlib
import threading
from typing import Optional, Dict, Any

from .exceptions import RequestsError
from .socket_engine import SocketEngine
from .http_parser import HTTPParser
from .response import Response


class _URLParser:
    """Phân tích URL thủ công, không dùng urllib."""

    def __init__(self, url: str) -> None:
        self.raw = url.strip()
        self.scheme = ""
        self.hostname = ""
        self.port: Optional[int] = None
        self.path = "/"
        self.query = ""
        self._parse()

    def _parse(self) -> None:
        rest = self.raw

        if "://" in rest:
            self.scheme, rest = rest.split("://", 1)
            self.scheme = self.scheme.lower()
        else:
            raise RequestsError(f"URL thiếu scheme: {self.raw}")

        if self.scheme not in ("http", "https"):
            raise RequestsError(
                f"Scheme không hỗ trợ: {self.scheme}"
            )

        if "#" in rest:
            rest = rest.split("#", 1)[0]

        if "?" in rest:
            rest, self.query = rest.split("?", 1)

        if "/" in rest:
            authority, path_part = rest.split("/", 1)
            self.path = "/" + path_part
        else:
            authority = rest
            self.path = "/"

        if "@" in authority:
            authority = authority.rsplit("@", 1)[1]

        if authority.startswith("["):
            bracket_end = authority.find("]")
            if bracket_end == -1:
                raise RequestsError(
                    f"URL IPv6 không hợp lệ: {self.raw}"
                )

            self.hostname = authority[1:bracket_end]
            after = authority[bracket_end + 1:]

            if after.startswith(":"):
                try:
                    self.port = int(after[1:])
                except ValueError:
                    raise RequestsError(
                        f"Port không hợp lệ trong URL: {self.raw}"
                    )

        elif ":" in authority:
            host_part, port_part = authority.rsplit(":", 1)
            self.hostname = host_part

            if port_part:
                try:
                    self.port = int(port_part)
                except ValueError:
                    raise RequestsError(
                        f"Port không hợp lệ trong URL: {self.raw}"
                    )

        else:
            self.hostname = authority

        if not self.hostname:
            raise RequestsError(
                f"URL không có hostname: {self.raw}"
            )

    @property
    def effective_port(self) -> int:
        if self.port is not None:
            return self.port
        return 443 if self.scheme == "https" else 80

    @property
    def use_tls(self) -> bool:
        return self.scheme == "https"

    @property
    def full_path(self) -> str:
        if self.query:
            return f"{self.path}?{self.query}"
        return self.path


class _FormEncoder:
    """Mã hóa dữ liệu form, không dùng urllib."""

    _SAFE = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        "abcdefghijklmnopqrstuvwxyz"
        "0123456789"
        "-_.~"
    )

    @classmethod
    def encode_value(cls, value: str) -> str:
        result = []
        for byte in value.encode("utf-8"):
            char = chr(byte)
            if char in cls._SAFE:
                result.append(char)
            elif char == " ":
                result.append("+")
            else:
                result.append(f"%{byte:02X}")
        return "".join(result)

    @classmethod
    def urlencode(cls, data: Dict[str, Any]) -> str:
        pairs = []
        for key, value in data.items():
            encoded_key = cls.encode_value(str(key))
            encoded_val = cls.encode_value(str(value))
            pairs.append(f"{encoded_key}={encoded_val}")
        return "&".join(pairs)


def _decompress_body(headers: Dict[str, str], body: bytes) -> bytes:
    """Giải nén gzip/deflate bằng zlib/gzip C nếu có."""
    if not body:
        return body

    encoding = headers.get("content-encoding", "").lower()

    if "gzip" in encoding or "x-gzip" in encoding:
        try:
            return gzip.decompress(body)
        except OSError:
            return body

    if "deflate" in encoding:
        try:
            return zlib.decompress(body)
        except zlib.error:
            try:
                return zlib.decompress(body, -zlib.MAX_WBITS)
            except zlib.error:
                return body

    return body


class RequestManager:
    """Quản lý HTTP request đồng bộ."""

    DEFAULT_HEADERS = {
        "User-Agent": "httpmas/1.0 (Socket-Based)",
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }

    _HEADER_PREFIX_CACHE: Dict[str, bytes] = {}
    _HEADER_CACHE_MAX = 512
    _HEADER_LOCK = threading.Lock()

    # FIX: Phương thức an toàn để retry (idempotent).
    _RETRYABLE_METHODS = {"GET", "HEAD", "OPTIONS"}

    def __init__(
        self, timeout: float = 10.0, max_retries: int = 2
    ) -> None:
        self._timeout = timeout
        self._engine = SocketEngine(
            default_timeout=timeout,
            max_retries=max_retries,
        )

    def request(
        self, method: str, url: str, **kwargs
    ) -> Response:
        return self._request(method.upper(), url, **kwargs)

    def get(
        self, url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        return self._request(
            "GET", url, headers=headers,
            params=params, timeout=timeout
        )

    def post(
        self, url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Any = None, json: Any = None,
        params: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        return self._request(
            "POST", url, headers=headers, data=data,
            json=json, params=params, timeout=timeout
        )

    def put(
        self, url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Any = None, json: Any = None,
        timeout: Optional[float] = None
    ) -> Response:
        return self._request(
            "PUT", url, headers=headers,
            data=data, json=json, timeout=timeout
        )

    def delete(
        self, url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        return self._request(
            "DELETE", url, headers=headers, timeout=timeout
        )

    def patch(
        self, url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Any = None, json: Any = None,
        timeout: Optional[float] = None
    ) -> Response:
        return self._request(
            "PATCH", url, headers=headers,
            data=data, json=json, timeout=timeout
        )

    def _discard_sock(self, sock: socket.socket) -> None:
        if sock is None:
            return

        discard = getattr(self._engine, "discard", None)
        if callable(discard):
            try:
                discard(sock)
                return
            except Exception:
                pass

        try:
            SocketEngine._close_socket(sock)
        except Exception:
            pass

    def _release_sock(
        self,
        parsed: "_URLParser",
        sock: socket.socket,
    ) -> None:
        if sock is None:
            return

        try:
            self._engine.release(
                parsed.hostname,
                parsed.effective_port,
                parsed.use_tls,
                sock,
                reusable=True,
            )
        except Exception:
            self._discard_sock(sock)

    @staticmethod
    def _infer_should_close(headers: Dict[str, str]) -> bool:
        connection_header = headers.get("connection", "").lower()
        transfer_encoding = headers.get(
            "transfer-encoding", ""
        ).lower()
        content_length = headers.get("content-length", "")

        if connection_header == "close":
            return True

        if "chunked" not in transfer_encoding and not content_length:
            return True

        return False

    @classmethod
    def _header_prefix(cls, key: str) -> bytes:
        key_str = str(key)

        prefix = cls._HEADER_PREFIX_CACHE.get(key_str)
        if prefix is not None:
            return prefix

        with cls._HEADER_LOCK:
            prefix = cls._HEADER_PREFIX_CACHE.get(key_str)
            if prefix is not None:
                return prefix

            prefix = f"{key_str}: ".encode("utf-8")

            if len(cls._HEADER_PREFIX_CACHE) >= cls._HEADER_CACHE_MAX:
                cls._HEADER_PREFIX_CACHE.clear()

            cls._HEADER_PREFIX_CACHE[key_str] = prefix

        return prefix

    @classmethod
    def _build_raw_request(
        cls,
        method: str,
        path: str,
        headers: Dict[str, str],
        body: bytes,
    ) -> bytes:
        parts = [
            f"{method} {path} HTTP/1.1\r\n".encode("utf-8")
        ]

        for key, value in headers.items():
            parts.append(cls._header_prefix(key))
            parts.append(str(value).encode("utf-8"))
            parts.append(b"\r\n")

        parts.append(b"\r\n")

        if body:
            parts.append(body)

        return b"".join(parts)

    def _request(
        self, method: str, url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Any = None, json: Any = None,
        params: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        """Thực thi HTTP request hoàn chỉnh.

        FIX: Thêm request-level retry cho stale pooled connections.
        Khi pooled socket chết mà health check không phát hiện,
        sendall/recv sẽ fail. Discard socket và retry với connection mới.
        Chỉ retry cho idempotent methods (GET/HEAD/OPTIONS).
        """
        start_time = time.monotonic()
        parsed = _URLParser(url)
        path = parsed.full_path

        if params:
            query_str = _FormEncoder.urlencode(params)
            if "?" in path:
                path += "&" + query_str
            else:
                path += "?" + query_str

        req_headers = dict(self.DEFAULT_HEADERS)
        req_headers["Host"] = parsed.hostname

        if headers:
            req_headers.update(headers)

        body = self._prepare_body(data, json, req_headers)
        raw_request = self._build_raw_request(
            method, path, req_headers, body
        )

        effective_timeout = (
            timeout if timeout is not None else self._timeout
        )

        # FIX: Request-level retry.
        # Attempt 0: thử bình thường (có thể dùng pooled socket).
        # Attempt 1: nếu fail vì stale socket, tạo connection mới.
        method_upper = method.upper()
        max_attempts = (
            2 if method_upper in self._RETRYABLE_METHODS else 1
        )

        last_exc: Optional[Exception] = None

        for attempt in range(max_attempts):
            sock = None

            try:
                sock = self._engine.connect(
                    parsed.hostname, parsed.effective_port,
                    use_tls=parsed.use_tls,
                    timeout=effective_timeout,
                )

                sock.sendall(raw_request)

                parser = HTTPParser(sock)
                parse_result = parser.parse()

                if len(parse_result) == 5:
                    (
                        status_code,
                        reason,
                        resp_headers,
                        resp_body,
                        should_close,
                    ) = parse_result
                else:
                    (
                        status_code,
                        reason,
                        resp_headers,
                        resp_body,
                    ) = parse_result
                    should_close = self._infer_should_close(
                        resp_headers
                    )

                resp_body = _decompress_body(
                    resp_headers, resp_body
                )

                elapsed = time.monotonic() - start_time

                if should_close:
                    self._discard_sock(sock)
                else:
                    self._release_sock(parsed, sock)

                return Response(
                    status_code=status_code,
                    reason=reason,
                    headers=resp_headers,
                    content=resp_body,
                    url=url,
                    elapsed=elapsed,
                )

            except RequestsError as exc:
                self._discard_sock(sock)
                last_exc = exc

                # FIX: Retry nếu là lỗi kết nối và còn attempt.
                if attempt + 1 < max_attempts:
                    continue

                raise

            except socket.timeout:
                self._discard_sock(sock)

                if attempt + 1 < max_attempts:
                    continue

                raise RequestsError(
                    f"Hết thời gian chờ khi gửi request "
                    f"tới {parsed.hostname}",
                    print_error=False,
                )

            except OSError as exc:
                self._discard_sock(sock)
                last_exc = exc

                # FIX: Retry nếu là lỗi kết nối và còn attempt.
                if attempt + 1 < max_attempts:
                    continue

                raise RequestsError(
                    f"Lỗi socket khi giao tiếp "
                    f"với {parsed.hostname}: {exc}",
                    print_error=False,
                )

        # Không nên tới đây, nhưng phòng hờ.
        if last_exc is not None:
            raise last_exc

        raise RequestsError(
            f"Request tới {parsed.hostname} thất bại",
            print_error=False,
        )

    def _prepare_body(
        self, data: Any, json: Any, headers: Dict[str, str]
    ) -> bytes:
        body = b""

        if json is not None:
            body = _json.dumps(
                json, ensure_ascii=False
            ).encode("utf-8")

            if "Content-Type" not in headers:
                headers["Content-Type"] = (
                    "application/json; charset=utf-8"
                )

        elif data is not None:
            if isinstance(data, bytes):
                body = data
            elif isinstance(data, str):
                body = data.encode("utf-8")
            elif isinstance(data, dict):
                body = _FormEncoder.urlencode(data).encode("utf-8")

                if "Content-Type" not in headers:
                    headers["Content-Type"] = (
                        "application/x-www-form-urlencoded"
                    )
            else:
                body = str(data).encode("utf-8")

        if body:
            headers["Content-Length"] = str(len(body))

        return body

    def close(self) -> None:
        self._engine.close_all()

    def __del__(self) -> None:
        try:
            self._engine.close_all()
        except Exception:
            pass


# ============================================================
# API MỨC MODULE - GIỐNG HỆT THƯ VIỆN REQUESTS GỐC
# ============================================================

_default_manager = RequestManager()
_default_async_manager = None


def _get_async_manager() -> Any:
    """Lấy singleton async (import trễ để tránh import vòng)."""
    global _default_async_manager

    if _default_async_manager is None:
        from .async_engine import AsyncRequestManager
        _default_async_manager = AsyncRequestManager()

    return _default_async_manager


def request(method: str, url: str, **kwargs) -> Response:
    return _default_manager.request(method, url, **kwargs)


def get(url: str, **kwargs) -> Response:
    return _default_manager.get(url, **kwargs)


def post(url: str, **kwargs) -> Response:
    return _default_manager.post(url, **kwargs)


def put(url: str, **kwargs) -> Response:
    return _default_manager.put(url, **kwargs)


def delete(url: str, **kwargs) -> Response:
    return _default_manager.delete(url, **kwargs)


def patch(url: str, **kwargs) -> Response:
    return _default_manager.patch(url, **kwargs)


def close() -> None:
    _default_manager.close()


async def async_request(
    method: str, url: str, **kwargs
) -> Response:
    mgr = _get_async_manager()
    return await mgr._request(method.upper(), url, **kwargs)


async def async_get(url: str, **kwargs) -> Response:
    return await _get_async_manager().async_get(url, **kwargs)


async def async_post(url: str, **kwargs) -> Response:
    return await _get_async_manager().async_post(url, **kwargs)


async def async_put(url: str, **kwargs) -> Response:
    return await _get_async_manager().async_put(url, **kwargs)


async def async_delete(url: str, **kwargs) -> Response:
    return await _get_async_manager().async_delete(url, **kwargs)


async def async_patch(url: str, **kwargs) -> Response:
    return await _get_async_manager().async_patch(url, **kwargs)


async def gather(*coros):
    return await _get_async_manager().gather(*coros)