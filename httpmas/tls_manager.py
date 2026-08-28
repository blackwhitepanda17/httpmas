"""Quản lý TLS/SSL cho httpmas."""

import ssl
import socket
import threading
from typing import Optional

from .exceptions import RequestsError


class TLSManager:
    """Quản lý kết nối TLS/SSL.

    Đảm bảo mọi kết nối HTTPS đều được mã hóa với cấu hình bảo mật cao nhất.
    Không cho phép bỏ qua xác minh chứng chỉ.
    """

    _context: Optional[ssl.SSLContext] = None
    _context_lock = threading.Lock()

    @classmethod
    def _create_context(cls) -> ssl.SSLContext:
        """Tạo SSLContext với cấu hình bảo mật cao."""
        context = ssl.create_default_context()

        context.minimum_version = ssl.TLSVersion.TLSv1_2

        context.set_ciphers(
            "ECDHE+AESGCM:ECDHE+CHACHA20:DHE+AESGCM:"
            "DHE+CHACHA20:!aNULL:!MD5:!DSS"
        )

        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED

        try:
            mode = getattr(ssl, "SESS_CACHE_CLIENT", None)
            if mode is not None and hasattr(
                context, "set_session_cache_mode"
            ):
                context.set_session_cache_mode(mode)
        except Exception:
            pass

        return context

    @classmethod
    def get_context(cls) -> ssl.SSLContext:
        """Lấy SSLContext dùng chung (singleton, thread-safe)."""
        if cls._context is None:
            with cls._context_lock:
                if cls._context is None:
                    try:
                        cls._context = cls._create_context()
                    except Exception as exc:
                        raise RequestsError(
                            f"Không thể khởi tạo TLS context: {exc}"
                        )

        return cls._context

    @classmethod
    def wrap_socket(
        cls, sock: socket.socket, hostname: str
    ) -> ssl.SSLSocket:
        """Bọc socket TCP bằng TLS.

        Tham số:
            sock: Socket TCP chưa mã hóa.
            hostname: Tên máy chủ để xác minh SNI và chứng chỉ.

        Trả về:
            ssl.SSLSocket đã được bọc TLS.
        """
        context = cls.get_context()

        try:
            return context.wrap_socket(
                sock, server_hostname=hostname
            )

        except ssl.SSLCertVerificationError as exc:
            try:
                sock.close()
            except OSError:
                pass
            raise RequestsError(
                f"Xác minh chứng chỉ thất bại cho {hostname}: {exc}"
            )

        except ssl.SSLError as exc:
            try:
                sock.close()
            except OSError:
                pass
            raise RequestsError(
                f"Lỗi TLS khi kết nối {hostname}: {exc}"
            )

        except OSError as exc:
            try:
                sock.close()
            except OSError:
                pass
            raise RequestsError(
                f"Lỗi kết nối TLS tới {hostname}: {exc}"
            )

    @classmethod
    def reset_context(cls) -> None:
        """Xóa SSLContext hiện tại."""
        with cls._context_lock:
            cls._context = None
