"""
AsyncEngine - Xử lý HTTP request bất đồng bộ.

Nâng cấp:
- AsyncConnectionPool + HostPool.
- Per-host semaphore, hạn chế handshake storm.
- Keep-alive timeout + health check.
- Retry transient cho GET/HEAD/OPTIONS với deadline tracking.
- DNS single-flight.
- gzip/deflate/br nếu có brotli.
- Parser trả should_close.
- Không block event loop.
- Không dùng requests/aiohttp làm backend.

FIX REGRESSION:
- Deadline tracking: không nhân đôi timeout khi retry.
- Không retry timeout (kể cả reused) để tránh p99 tăng.
- Cleanup idle theo interval thay vì mỗi lần acquire.
"""

import asyncio
import socket
import ssl
import time
import json as _json
import gzip
import zlib
from typing import Optional, Dict, Any, List, Tuple

from .exceptions import RequestsError, _ColorPrinter
from .tls_manager import TLSManager
from .response import Response
from .requests import _URLParser, _FormEncoder
from .dns import DNSCache

try:
    import brotli
    _BROTLI_AVAILABLE = True
except ImportError:
    _BROTLI_AVAILABLE = False

_ACCEPT_ENCODING = "gzip, deflate"
if _BROTLI_AVAILABLE:
    _ACCEPT_ENCODING += ", br"


class _TransientError(Exception):
    """Lỗi tạm thời có thể retry, không tự in ra terminal."""


async def _wait_writer(writer) -> None:
    """Chờ writer đóng xong, bỏ qua lỗi."""
    try:
        await writer.wait_closed()
    except Exception:
        pass


def _close_writer_now(writer) -> None:
    """Đóng writer ngay, cố gắng chờ wait_closed trong nền."""
    if writer is None:
        return

    try:
        writer.close()
    except Exception:
        pass

    try:
        loop = asyncio.get_running_loop()
        if not loop.is_closed():
            task = asyncio.ensure_future(_wait_writer(writer))
            task.add_done_callback(
                lambda t: t.exception()
                if not t.cancelled() else None
            )
    except RuntimeError:
        pass


def _decompress_body(headers: Dict[str, str], body: bytes) -> bytes:
    """Giải nén gzip/deflate/br nếu server trả về body nén."""
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

    if "br" in encoding and _BROTLI_AVAILABLE:
        try:
            return brotli.decompress(body)
        except Exception:
            return body

    return body


class ErrorDispatcher:
    """Bộ phân phối lỗi ưu tiên cao cho async."""

    def __init__(self) -> None:
        self._queue: Optional[asyncio.Queue] = None
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._running:
            return
        self._queue = asyncio.Queue()
        self._running = True
        self._task = asyncio.ensure_future(self._dispatch_loop())

    async def _dispatch_loop(self) -> None:
        while self._running:
            try:
                message = await asyncio.wait_for(
                    self._queue.get(), timeout=0.1
                )
                _ColorPrinter.print_error(message)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def dispatch(self, message: str) -> None:
        if self._queue is not None:
            await self._queue.put(message)
        else:
            _ColorPrinter.print_error(message)

    def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None


class _HostPool:
    """Pool cho một host:port:protocol."""

    __slots__ = ("idle", "active", "semaphore", "max_keepalive")

    def __init__(
        self,
        max_keepalive: int,
        max_active: int,
    ) -> None:
        self.idle: List[Tuple[Any, Any, float]] = []
        self.active = 0
        self.semaphore = asyncio.Semaphore(max_active)
        self.max_keepalive = max_keepalive


class AsyncConnectionPool:
    """Connection pool async.

    FIX REGRESSION:
    - Cleanup idle theo interval (5s) thay vì mỗi lần acquire.
    - Giữ nguyên semaphore + LIFO.
    """

    CLEANUP_INTERVAL = 5.0

    def __init__(
        self,
        max_per_host: int = 12,
        max_keepalive: int = 32,
        keepalive_timeout: float = 60.0,
    ) -> None:
        self._max_per_host = int(max_per_host)
        self._max_keepalive = int(max_keepalive)
        self._keepalive_timeout = float(keepalive_timeout)
        self._hosts: Dict[Tuple[str, int, bool], _HostPool] = {}
        self._last_cleanup: float = 0.0

    def _get_host_pool(
        self,
        key: Tuple[str, int, bool],
    ) -> _HostPool:
        hp = self._hosts.get(key)
        if hp is None:
            hp = _HostPool(
                self._max_keepalive,
                self._max_per_host,
            )
            self._hosts[key] = hp
        return hp

    @staticmethod
    def _is_alive(reader, writer) -> bool:
        """Health check nhanh trước khi reuse."""
        try:
            if reader is None or writer is None:
                return False
        except Exception:
            return False

        try:
            if writer.is_closing():
                return False
        except AttributeError:
            try:
                if writer.transport.is_closing():
                    return False
            except Exception:
                return False
        except Exception:
            return False

        try:
            if reader.at_eof():
                return False
        except Exception:
            return False

        return True

    def _cleanup_expired(self, hp: _HostPool) -> None:
        """Dọn idle connection hết hạn hoặc chết."""
        if not hp.idle:
            return

        now = time.monotonic()
        keep = []

        for item in hp.idle:
            reader, writer, ts = item

            if now - ts > self._keepalive_timeout:
                _close_writer_now(writer)
                continue

            if not self._is_alive(reader, writer):
                _close_writer_now(writer)
                continue

            keep.append(item)

        hp.idle = keep

    def _maybe_cleanup_all(self) -> None:
        """FIX: Cleanup theo interval thay vì mỗi lần acquire."""
        now = time.monotonic()
        if now - self._last_cleanup < self.CLEANUP_INTERVAL:
            return
        self._last_cleanup = now

        for hp in self._hosts.values():
            self._cleanup_expired(hp)

    async def acquire(
        self,
        key: Tuple[str, int, bool],
        timeout: float,
        connector,
        host: str,
        port: int,
        use_tls: bool,
    ) -> Tuple[Any, Any, bool]:
        """Lấy connection từ pool hoặc tạo mới.

        Trả về:
            (reader, writer, reused)
        """
        hp = self._get_host_pool(key)

        try:
            await asyncio.wait_for(
                hp.semaphore.acquire(),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            raise _TransientError(
                f"Hết thời gian chờ connection pool cho {host}:{port}"
            )

        try:
            # FIX: Cleanup theo interval, không phải mỗi lần acquire.
            self._maybe_cleanup_all()

            # LIFO: connection nóng được ưu tiên.
            while hp.idle:
                reader, writer, _ = hp.idle.pop()

                if self._is_alive(reader, writer):
                    hp.active += 1
                    return reader, writer, True

                _close_writer_now(writer)

            reader, writer = await connector(
                host,
                port,
                use_tls,
                timeout,
            )

            hp.active += 1
            return reader, writer, False

        except Exception:
            hp.semaphore.release()
            raise

    def release(
        self,
        key: Tuple[str, int, bool],
        reader,
        writer,
        reusable: bool = True,
    ) -> None:
        """Trả connection về pool."""
        hp = self._hosts.get(key)

        if hp is None:
            _close_writer_now(writer)
            return

        hp.active = max(0, hp.active - 1)

        if (
            reusable
            and self._is_alive(reader, writer)
            and len(hp.idle) < hp.max_keepalive
        ):
            hp.idle.append((reader, writer, time.monotonic()))
        else:
            _close_writer_now(writer)

        hp.semaphore.release()

    def discard(
        self,
        key: Tuple[str, int, bool],
        writer,
    ) -> None:
        """Đóng connection, không trả về pool."""
        hp = self._hosts.get(key)

        if hp is not None:
            hp.active = max(0, hp.active - 1)
            hp.semaphore.release()

        _close_writer_now(writer)

    async def close_all(self) -> None:
        """Đóng toàn bộ idle connection."""
        for hp in self._hosts.values():
            for reader, writer, _ in hp.idle:
                _close_writer_now(writer)

            hp.idle.clear()

        self._hosts.clear()


class AsyncSocketEngine:
    """Quản lý kết nối socket bất đồng bộ."""

    STREAM_LIMIT = 4 * 1024 * 1024
    SOCKET_BUFFER = 4 * 1024 * 1024

    def __init__(self, default_timeout: float = 10.0) -> None:
        self._timeout = default_timeout

        self._pool = AsyncConnectionPool(
            max_per_host=12,
            max_keepalive=32,
            keepalive_timeout=60.0,
        )

        self._dns = DNSCache(
            ttl=300.0,
            max_entries=1024,
        )

    @classmethod
    def _tune_writer(cls, writer) -> None:
        """Áp socket options lên socket underlying nếu lấy được."""
        try:
            sock = writer.get_extra_info("socket")
            if sock is None:
                return

            try:
                sock.setsockopt(
                    socket.IPPROTO_TCP,
                    socket.TCP_NODELAY,
                    1,
                )
            except OSError:
                pass

            try:
                sock.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_KEEPALIVE,
                    1,
                )
            except OSError:
                pass

            try:
                sock.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_SNDBUF,
                    cls.SOCKET_BUFFER,
                )
            except OSError:
                pass

            try:
                sock.setsockopt(
                    socket.SOL_SOCKET,
                    socket.SO_RCVBUF,
                    cls.SOCKET_BUFFER,
                )
            except OSError:
                pass

        except Exception:
            pass

    async def connect(
        self,
        host: str,
        port: int,
        use_tls: bool = False,
        timeout: Optional[float] = None,
    ) -> Tuple[Any, Any, bool]:
        """Mở kết nối bất đồng bộ.

        Trả về:
            (reader, writer, reused)
        """
        effective_timeout = (
            timeout if timeout is not None else self._timeout
        )

        key = (host, port, use_tls)

        return await self._pool.acquire(
            key,
            effective_timeout,
            self._open_connection,
            host,
            port,
            use_tls,
        )

    async def _open_connection(
        self,
        host: str,
        port: int,
        use_tls: bool,
        timeout: float,
    ):
        """Tạo kết nối mới với DNS cache + IPv4 priority."""
        ssl_context = TLSManager.get_context() if use_tls else None

        try:
            infos = await self._dns.async_resolve(host)
        except RequestsError as exc:
            raise _TransientError(str(exc))

        infos = DNSCache.sort_ipv4_first(infos)

        last_error: Optional[Exception] = None

        for info in infos:
            try:
                ip = info[4][0]
            except (IndexError, TypeError):
                continue

            try:
                if use_tls:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(
                            ip,
                            port,
                            ssl=ssl_context,
                            server_hostname=host,
                            limit=self.STREAM_LIMIT,
                        ),
                        timeout=timeout,
                    )
                else:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(
                            ip,
                            port,
                            limit=self.STREAM_LIMIT,
                        ),
                        timeout=timeout,
                    )

                self._tune_writer(writer)
                return reader, writer

            except asyncio.TimeoutError as exc:
                last_error = exc

            except ssl.SSLCertVerificationError as exc:
                raise RequestsError(
                    f"Xác minh chứng chỉ thất bại cho {host}: {exc}",
                    print_error=False,
                )

            except ssl.SSLError as exc:
                raise RequestsError(
                    f"Lỗi TLS khi kết nối {host}: {exc}",
                    print_error=False,
                )

            except OSError as exc:
                last_error = exc

        raise _TransientError(
            f"Không thể kết nối async tới {host}:{port}: {last_error}"
        )

    def release(
        self,
        host: str,
        port: int,
        use_tls: bool,
        reader,
        writer,
        reusable: bool = True,
    ) -> None:
        """Trả kết nối về pool."""
        key = (host, port, use_tls)
        self._pool.release(key, reader, writer, reusable)

    def discard(
        self,
        host: str,
        port: int,
        use_tls: bool,
        writer,
    ) -> None:
        """Đóng kết nối, không trả về pool."""
        key = (host, port, use_tls)
        self._pool.discard(key, writer)

    async def close_all(self) -> None:
        """Đóng toàn bộ kết nối trong pool."""
        await self._pool.close_all()


class AsyncHTTPParser:
    """Phân tích HTTP response từ asyncio StreamReader."""

    __slots__ = ("_reader", "_method")

    def __init__(self, reader, method: str = "GET") -> None:
        self._reader = reader
        self._method = method.upper()

    async def parse(self):
        """Phân tích response bất đồng bộ.

        Trả về:
            (status_code, reason, headers, body, should_close)
        """
        try:
            head = await self._reader.readuntil(b"\r\n\r\n")
        except asyncio.IncompleteReadError as exc:
            raise _TransientError(
                f"Kết nối bị đóng khi đọc header: {exc}"
            )
        except (ConnectionError, asyncio.TimeoutError, OSError) as exc:
            raise _TransientError(
                f"Lỗi kết nối khi đọc header: {exc}"
            )

        head = head[:-4]

        try:
            head_str = head.decode("latin-1")
        except UnicodeDecodeError:
            head_str = head.decode("utf-8", errors="replace")

        lines = head_str.split("\r\n")

        if not lines or not lines[0]:
            raise RequestsError(
                "Status line không hợp lệ",
                print_error=False,
            )

        try:
            parts = lines[0].split(" ", 2)
            status_code = int(parts[1])
            reason = parts[2] if len(parts) > 2 else ""
            http_version = parts[0].upper()
        except (IndexError, ValueError) as exc:
            raise RequestsError(
                f"Status line không hợp lệ: {exc}",
                print_error=False,
            )

        headers: Dict[str, str] = {}

        for line in lines[1:]:
            if not line:
                continue

            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.strip().lower()] = value.strip()

        connection_header = headers.get(
            "connection", ""
        ).lower()

        transfer_encoding = headers.get(
            "transfer-encoding", ""
        ).lower()

        content_length = headers.get(
            "content-length", ""
        )

        no_body = (
            self._method == "HEAD"
            or status_code in (204, 304)
            or 100 <= status_code < 200
        )

        should_close = False

        if connection_header == "close":
            should_close = True
        elif http_version == "HTTP/1.0" and connection_header != "keep-alive":
            should_close = True
        elif (
            not no_body
            and "chunked" not in transfer_encoding
            and not content_length
        ):
            should_close = True

        if no_body:
            body = b""
        else:
            body = await self._read_body(headers)

        return status_code, reason, headers, body, should_close

    async def _read_body(
        self, headers: Dict[str, str]
    ) -> bytes:
        """Đọc body dựa trên headers."""
        transfer_encoding = headers.get(
            "transfer-encoding", ""
        ).lower()

        if "chunked" in transfer_encoding:
            return await self._read_chunked()

        content_length = headers.get("content-length", "")

        if content_length:
            try:
                length = int(content_length)
            except ValueError:
                raise RequestsError(
                    f"Content-Length không hợp lệ: "
                    f"{content_length}",
                    print_error=False,
                )

            if length == 0:
                return b""

            try:
                return await self._reader.readexactly(length)
            except asyncio.IncompleteReadError as exc:
                raise _TransientError(
                    f"Kết nối bị đóng khi đọc body: {exc}"
                )
            except (ConnectionError, asyncio.TimeoutError, OSError) as exc:
                raise _TransientError(
                    f"Lỗi kết nối khi đọc body: {exc}"
                )

        try:
            return await self._reader.read(-1)
        except (ConnectionError, asyncio.TimeoutError, OSError) as exc:
            raise _TransientError(
                f"Lỗi kết nối khi đọc body: {exc}"
            )
        except Exception as exc:
            raise RequestsError(
                f"Lỗi khi đọc body: {exc}",
                print_error=False,
            )

    async def _read_chunked(self) -> bytes:
        """Đọc body chunked bất đồng bộ."""
        chunks = []

        while True:
            try:
                size_line = await self._reader.readuntil(b"\r\n")
            except asyncio.IncompleteReadError as exc:
                raise _TransientError(
                    f"Kết nối bị đóng khi đọc chunked: {exc}"
                )

            try:
                size_str = size_line.decode("ascii").split(
                    ";"
                )[0].strip()
                chunk_size = int(size_str, 16)
            except ValueError as exc:
                raise RequestsError(
                    f"Chunk size không hợp lệ: {exc}",
                    print_error=False,
                )

            if chunk_size == 0:
                while True:
                    try:
                        trailer = (
                            await self._reader.readuntil(b"\r\n")
                        )
                        if trailer.strip() == b"":
                            break
                    except asyncio.IncompleteReadError:
                        break
                break

            try:
                chunk_data = await self._reader.readexactly(
                    chunk_size
                )
            except asyncio.IncompleteReadError as exc:
                raise _TransientError(
                    f"Chunk bị cắt ngắn: {exc}"
                )

            if chunk_data:
                chunks.append(chunk_data)

            try:
                await self._reader.readuntil(b"\r\n")
            except asyncio.IncompleteReadError:
                break

        return b"".join(chunks)


class AsyncRequestManager:
    """Quản lý HTTP request bất đồng bộ.

    FIX REGRESSION:
    - Deadline tracking: tổng thời gian không vượt timeout.
    - Không retry timeout (kể cả reused).
    - Chỉ retry stale connection (EOF/reset trên reused socket).
    """

    DEFAULT_HEADERS = {
        "User-Agent": "httpmas/1.0 (Async-Socket-Based)",
        "Accept": "*/*",
        "Accept-Encoding": _ACCEPT_ENCODING,
        "Connection": "keep-alive",
    }

    SAFE_RETRY_METHODS = {"GET", "HEAD", "OPTIONS"}
    MAX_AUTO_RETRIES = 1

    _HEADER_PREFIX_CACHE: Dict[str, bytes] = {}
    _HEADER_CACHE_MAX = 512

    def __init__(self, timeout: float = 10.0) -> None:
        self._timeout = timeout

        self._engine = AsyncSocketEngine(
            default_timeout=timeout
        )

        self._error_dispatcher = ErrorDispatcher()

    async def async_get(
        self, url: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        return await self._request(
            "GET", url, headers=headers,
            params=params, timeout=timeout
        )

    async def async_post(
        self, url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Any = None, json: Any = None,
        params: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        return await self._request(
            "POST", url, headers=headers, data=data,
            json=json, params=params, timeout=timeout
        )

    async def async_put(
        self, url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Any = None, json: Any = None,
        timeout: Optional[float] = None
    ) -> Response:
        return await self._request(
            "PUT", url, headers=headers, data=data,
            json=json, timeout=timeout
        )

    async def async_delete(
        self, url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        return await self._request(
            "DELETE", url, headers=headers, timeout=timeout
        )

    async def async_patch(
        self, url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Any = None, json: Any = None,
        timeout: Optional[float] = None
    ) -> Response:
        return await self._request(
            "PATCH", url, headers=headers, data=data,
            json=json, timeout=timeout
        )

    async def gather(self, *coros) -> List[Any]:
        """Chạy nhiều request đồng thời, lỗi ưu tiên hiển thị ngay."""
        await self._error_dispatcher.start()

        async def _wrapper(coro):
            try:
                return await coro
            except RequestsError as exc:
                return exc
            except Exception as exc:
                await self._error_dispatcher.dispatch(str(exc))
                return exc

        tasks = [
            asyncio.ensure_future(_wrapper(c)) for c in coros
        ]

        results = await asyncio.gather(
            *tasks, return_exceptions=False
        )

        self._error_dispatcher.stop()
        return list(results)

    @classmethod
    def _header_prefix(cls, key: str) -> bytes:
        key_str = str(key)
        cache = cls._HEADER_PREFIX_CACHE

        prefix = cache.get(key_str)
        if prefix is not None:
            return prefix

        prefix = f"{key_str}: ".encode("utf-8")

        if len(cache) >= cls._HEADER_CACHE_MAX:
            cache.clear()

        cache[key_str] = prefix
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

    @staticmethod
    def _make_final_error(exc: Exception) -> RequestsError:
        """Chuyển lỗi nội bộ thành RequestsError public."""
        if isinstance(exc, RequestsError):
            return exc

        if isinstance(exc, asyncio.TimeoutError):
            message = "Hết thời gian chờ khi gửi/đọc response"
        else:
            message = str(getattr(exc, "message", exc))

        if not message:
            message = exc.__class__.__name__

        try:
            return RequestsError(message, print_error=True)
        except TypeError:
            return RequestsError(message)

    @classmethod
    def _should_retry(
        cls,
        method: str,
        exc: Exception,
        reused: bool,
    ) -> bool:
        """Quyết định có retry transient hay không.

        FIX REGRESSION:
        - KHÔNG retry timeout (kể cả reused).
          Trước đây: return reused cho TimeoutError
          → retry sau 15s timeout → tổng 30s → p99 = 31s.
        - Chỉ retry khi reused connection bị stale
          (EOF/reset, không phải timeout).
        """
        if method not in cls.SAFE_RETRY_METHODS:
            return False

        # FIX: Không retry timeout. Timeout là timeout.
        # Retry timeout chỉ nhân đôi latency.
        if isinstance(exc, asyncio.TimeoutError):
            return False

        if isinstance(
            exc,
            (
                _TransientError,
                ConnectionError,
                BrokenPipeError,
            ),
        ):
            msg = str(exc).lower()

            # Không retry nếu lỗi là timeout bên trong _TransientError.
            if "timeout" in msg or "thời gian chờ" in msg:
                return False

            # Chỉ retry khi reused connection bị stale.
            return reused

        if isinstance(exc, OSError):
            return reused

        return False

    async def _request(
        self, method: str, url: str,
        headers: Optional[Dict[str, str]] = None,
        data: Any = None, json: Any = None,
        params: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None
    ) -> Response:
        """Thực thi HTTP request bất đồng bộ hoàn chỉnh.

        FIX REGRESSION: Deadline tracking.
        Tổng thời gian tất cả attempts không vượt effective_timeout.
        """
        method_upper = method.upper()

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
            method_upper, path, req_headers, body
        )

        effective_timeout = (
            timeout if timeout is not None else self._timeout
        )

        attempts = (
            self.MAX_AUTO_RETRIES + 1
            if method_upper in self.SAFE_RETRY_METHODS
            else 1
        )

        # FIX: Deadline tracking.
        # Tổng thời gian tất cả attempts không vượt effective_timeout.
        deadline = time.monotonic() + effective_timeout

        last_exc: Optional[Exception] = None

        for attempt in range(attempts):
            reader = None
            writer = None
            reused = False

            # FIX: Tính thời gian còn lại trước mỗi attempt.
            remaining = deadline - time.monotonic()

            if remaining <= 0.5:
                # Không đủ thời gian cho attempt mới.
                break

            try:
                start_time = time.monotonic()

                reader, writer, reused = await self._engine.connect(
                    parsed.hostname,
                    parsed.effective_port,
                    parsed.use_tls,
                    remaining,  # FIX: pass remaining, không phải full timeout
                )

                return await self._send_and_parse(
                    method_upper,
                    parsed,
                    url,
                    raw_request,
                    reader,
                    writer,
                    start_time,
                )

            except ssl.SSLError as exc:
                if writer is not None:
                    self._engine.discard(
                        parsed.hostname,
                        parsed.effective_port,
                        parsed.use_tls,
                        writer,
                    )
                raise RequestsError(
                    f"Lỗi TLS khi giao tiếp với {parsed.hostname}: {exc}",
                    print_error=False,
                )

            except RequestsError:
                if writer is not None:
                    self._engine.discard(
                        parsed.hostname,
                        parsed.effective_port,
                        parsed.use_tls,
                        writer,
                    )
                raise

            except (
                _TransientError,
                asyncio.TimeoutError,
                ConnectionError,
                BrokenPipeError,
                OSError,
            ) as exc:
                if writer is not None:
                    self._engine.discard(
                        parsed.hostname,
                        parsed.effective_port,
                        parsed.use_tls,
                        writer,
                    )

                last_exc = exc

                if not self._should_retry(
                    method_upper,
                    exc,
                    reused,
                ):
                    raise self._make_final_error(exc)

                if attempt + 1 >= attempts:
                    raise self._make_final_error(exc)

                # FIX: Không sleep cho reused stale connection.
                # Retry ngay với thời gian còn lại.
                if reused:
                    await asyncio.sleep(0.01)
                else:
                    await asyncio.sleep(0.05 * (attempt + 1))

        raise self._make_final_error(last_exc)

    async def _send_and_parse(
        self,
        method: str,
        parsed: _URLParser,
        url: str,
        raw_request: bytes,
        reader,
        writer,
        start_time: float,
    ) -> Response:
        """Gửi request và parse response."""
        try:
            writer.write(raw_request)
            await writer.drain()

            parser = AsyncHTTPParser(reader, method=method)

            (
                status_code,
                reason,
                resp_headers,
                resp_body,
                should_close,
            ) = await parser.parse()

        except (
            _TransientError,
            asyncio.TimeoutError,
            ConnectionError,
            BrokenPipeError,
            OSError,
        ):
            self._engine.discard(
                parsed.hostname,
                parsed.effective_port,
                parsed.use_tls,
                writer,
            )
            raise

        except RequestsError:
            self._engine.discard(
                parsed.hostname,
                parsed.effective_port,
                parsed.use_tls,
                writer,
            )
            raise

        resp_body = _decompress_body(resp_headers, resp_body)

        elapsed = time.monotonic() - start_time

        if should_close:
            self._engine.discard(
                parsed.hostname,
                parsed.effective_port,
                parsed.use_tls,
                writer,
            )
        else:
            self._engine.release(
                parsed.hostname,
                parsed.effective_port,
                parsed.use_tls,
                reader,
                writer,
                reusable=True,
            )

        return Response(
            status_code=status_code,
            reason=reason,
            headers=resp_headers,
            content=resp_body,
            url=url,
            elapsed=elapsed,
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
                body = _FormEncoder.urlencode(data).encode(
                    "utf-8"
                )

                if "Content-Type" not in headers:
                    headers["Content-Type"] = (
                        "application/x-www-form-urlencoded"
                    )
            else:
                body = str(data).encode("utf-8")

        if body:
            headers["Content-Length"] = str(len(body))

        return body

    async def close(self) -> None:
        await self._engine.close_all()