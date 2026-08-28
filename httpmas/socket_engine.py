"""
Tầng xử lý socket TCP cho httpmas.
Nâng cấp:
Pool sync 32 connection/host.
Dùng DNSCache.
Ưu tiên IPv4.
Socket buffer 256KB (phù hợp Android kernel).
TCP_NODELAY + SO_KEEPALIVE.
Keep-alive reuse.
Health check nhẹ khi lấy connection từ pool.
"""

import socket
import time
import threading
import select
import ssl as _ssl
from typing import Optional, Dict, Tuple

from .exceptions import RequestsError
from .tls_manager import TLSManager
from .dns import DNSCache


class SocketEngine:
    """Quản lý kết nối TCP socket với hỗ trợ keep-alive."""

    MAX_POOL_PER_HOST = 32
    # FIX: 256KB thay vì 4MB.
    # Android kernel TCP buffer thường 128-256KB.
    # Set 4MB bị kernel ignore, mất thêm syscall.
    SOCKET_BUFFER = 256 * 1024

    def __init__(
        self,
        default_timeout: float = 10.0,
        max_retries: int = 2,
    ) -> None:
        self._timeout = default_timeout
        self._max_retries = max_retries

        self._pool: Dict[Tuple[str, int, bool], list] = {}
        self._lock = threading.Lock()

        self._dns = DNSCache(
            ttl=300.0,
            max_entries=1024,
        )

    @staticmethod
    def _address_for(sockaddr: tuple, port: int) -> tuple:
        try:
            if len(sockaddr) == 2:
                return sockaddr[0], port

            if len(sockaddr) == 4:
                return sockaddr[0], port, sockaddr[2], sockaddr[3]

        except (IndexError, TypeError):
            pass

        return sockaddr

    @classmethod
    def _tune_socket(cls, sock: socket.socket) -> None:
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

    def connect(
        self,
        host: str,
        port: int,
        use_tls: bool = False,
        timeout: Optional[float] = None,
    ) -> socket.socket:
        effective_timeout = (
            timeout if timeout is not None else self._timeout
        )

        key = (host, port, use_tls)
        pooled = self._get_from_pool(key)

        if pooled is not None:
            try:
                pooled.settimeout(effective_timeout)
                return pooled
            except OSError:
                self._close_socket(pooled)

        last_error: Optional[Exception] = None
        attempts = self._max_retries + 1

        for attempt in range(attempts):
            try:
                infos = self._dns.resolve(host)
                infos = DNSCache.sort_ipv4_first(infos)
            except RequestsError as exc:
                infos = []
                last_error = exc

            for info in infos:
                family, socktype, proto, _, sockaddr = info
                sock: Optional[socket.socket] = None

                try:
                    sock = socket.socket(
                        family,
                        socktype,
                        proto,
                    )

                    sock.settimeout(effective_timeout)
                    self._tune_socket(sock)

                    address = self._address_for(sockaddr, port)
                    sock.connect(address)

                    if use_tls:
                        sock = TLSManager.wrap_socket(sock, host)

                    return sock

                except RequestsError:
                    self._close_socket(sock)
                    raise

                except OSError as exc:
                    last_error = exc
                    self._close_socket(sock)

            if attempt < self._max_retries:
                time.sleep(0.1 * (attempt + 1))

        raise RequestsError(
            f"Không thể kết nối tới {host}:{port} sau "
            f"{attempts} lần thử: {last_error}",
            print_error=False,
        )

    def release(
        self,
        host: str,
        port: int,
        use_tls: bool,
        sock: socket.socket,
        reusable: bool = True,
    ) -> None:
        if sock is None:
            return

        if not reusable:
            self._close_socket(sock)
            return

        try:
            if sock.fileno() < 0:
                self._close_socket(sock)
                return
        except (OSError, ValueError):
            self._close_socket(sock)
            return

        key = (host, port, use_tls)

        with self._lock:
            if key not in self._pool:
                self._pool[key] = []

            if len(self._pool[key]) < self.MAX_POOL_PER_HOST:
                self._pool[key].append(sock)
            else:
                self._close_socket(sock)

    def discard(self, sock: socket.socket) -> None:
        self._close_socket(sock)

    def _get_from_pool(
        self,
        key: Tuple[str, int, bool],
    ) -> Optional[socket.socket]:
        """Lấy socket nhàn rỗi từ pool.

        FIX: Giảm syscall overhead.
        - Bỏ select() cho SSLSocket (syscall nặng nhất trên Android).
        - Giữ fileno() + pending() check cho SSL (nhẹ, không syscall).
        - Giữ MSG_PEEK cho socket thường (1 syscall).
        - Request-level retry trong requests.py làm safety net
          cho các connection chết mà health check không phát hiện.
        """
        with self._lock:
            conns = self._pool.get(key, [])

            while conns:
                sock = conns.pop()

                try:
                    if sock.fileno() < 0:
                        self._close_socket(sock)
                        continue
                except (OSError, ValueError):
                    self._close_socket(sock)
                    continue

                try:
                    if isinstance(sock, _ssl.SSLSocket):
                        # FIX: Bỏ select() cho SSLSocket.
                        # select() là syscall nặng nhất trên Android.
                        # Chỉ giữ pending() check (không syscall).
                        # Request-level retry trong requests.py
                        # sẽ xử lý nếu connection thực sự chết.
                        if sock.pending() > 0:
                            self._close_socket(sock)
                            continue

                        sock.settimeout(self._timeout)
                        return sock

                    else:
                        # Socket thường: giữ MSG_PEEK (1 syscall nhẹ).
                        sock.settimeout(0.0)

                        try:
                            data = sock.recv(1, socket.MSG_PEEK)

                            if data:
                                self._close_socket(sock)
                                continue

                        except BlockingIOError:
                            pass
                        except OSError:
                            self._close_socket(sock)
                            continue

                        sock.settimeout(self._timeout)
                        return sock

                except (OSError, ValueError, _ssl.SSLError):
                    self._close_socket(sock)

        return None

    @staticmethod
    def _close_socket(sock: socket.socket) -> None:
        if sock is None:
            return

        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

        try:
            sock.close()
        except OSError:
            pass

    def close_all(self) -> None:
        with self._lock:
            for conns in self._pool.values():
                for sock in conns:
                    self._close_socket(sock)

            self._pool.clear()