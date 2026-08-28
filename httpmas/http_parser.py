"""Trình phân tích cú pháp HTTP response."""

import socket
from typing import Dict, Tuple

from .exceptions import RequestsError


class HTTPParser:
    """Phân tích HTTP response từ luồng byte nhận qua socket."""
    def __init__(self, sock: socket.socket) -> None:
        """Khởi tạo parser với socket nguồn."""
        self._sock = sock
        self._buf = bytearray()
        self._offset = 0

    @property
    def _available(self) -> int:
        """Số byte còn đang chờ xử lý trong buffer."""
        return len(self._buf) - self._offset

    def _maybe_compact(self) -> None:
        """Dọn buffer khi phần đã tiêu thụ quá lớn."""
        if self._offset > 131072 and self._offset * 2 > len(self._buf):
            self._buf = self._buf[self._offset:]
            self._offset = 0

    def _recv_more(self) -> bool:
        """Nhận thêm dữ liệu từ socket vào buffer, block 1MB."""
        try:
            data = self._sock.recv(1048576)
        except socket.timeout:
            raise RequestsError(
                "Hết thời gian chờ khi đọc dữ liệu từ máy chủ"
            )
        except OSError as exc:
            raise RequestsError(f"Lỗi khi đọc dữ liệu: {exc}")

        if not data:
            return False

        self._maybe_compact()
        self._buf.extend(data)
        return True

    def _read_head(self) -> bytes:
        """Đọc toàn bộ phần head cho tới \\r\\n\\r\\n."""
        sep = b"\r\n\r\n"

        while True:
            idx = self._buf.find(sep, self._offset)

            if idx >= 0:
                head = bytes(self._buf[self._offset:idx])
                self._offset = idx + 4
                self._maybe_compact()
                return head

            if not self._recv_more():
                raise RequestsError(
                    "Kết nối bị đóng khi đang đọc header"
                )

    def _read_line(self) -> bytes:
        """Đọc một dòng kết thúc bằng CRLF từ buffer."""
        while True:
            idx = self._buf.find(b"\r\n", self._offset)

            if idx >= 0:
                line = bytes(self._buf[self._offset:idx])
                self._offset = idx + 2
                self._maybe_compact()
                return line

            if not self._recv_more():
                if self._available:
                    line = bytes(self._buf[self._offset:])
                    self._offset = len(self._buf)
                    return line

                raise RequestsError(
                    "Kết nối bị đóng khi đang đọc header"
                )

    def _read_bytes(self, count: int) -> bytes:
        """Đọc chính xác count byte từ buffer/socket."""
        while self._available < count:
            if not self._recv_more():
                break

        if self._available < count:
            raise RequestsError(
                f"Kết nối bị đóng khi đang đọc body "
                f"(cần {count} byte, nhận {self._available} byte)"
            )

        data = bytes(
            self._buf[self._offset:self._offset + count]
        )
        self._offset += count
        self._maybe_compact()
        return data

    def parse(self) -> Tuple[int, str, Dict[str, str], bytes, bool]:
        """Phân tích toàn bộ HTTP response.

        Trả về:
            Tuple gồm:
            (
                status_code,
                reason,
                headers_dict,
                body_bytes,
                should_close,
            )
        """
        head_bytes = self._read_head()

        try:
            head_str = head_bytes.decode("latin-1")
        except UnicodeDecodeError:
            head_str = head_bytes.decode("utf-8", errors="replace")

        lines = head_str.split("\r\n")

        if not lines:
            raise RequestsError("Status line không hợp lệ")

        try:
            parts = lines[0].split(" ", 2)
            status_code = int(parts[1])
            reason = parts[2] if len(parts) > 2 else ""
            http_version = parts[0].upper()
        except (IndexError, ValueError) as exc:
            raise RequestsError(
                f"Status line không hợp lệ: {exc}"
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
            status_code in (204, 304)
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
            body = self._read_body(headers)

        return status_code, reason, headers, body, should_close

    def _read_body(self, headers: Dict[str, str]) -> bytes:
        """Đọc body dựa trên headers."""
        transfer_encoding = headers.get(
            "transfer-encoding", ""
        ).lower()

        if "chunked" in transfer_encoding:
            return self._read_chunked_body()

        content_length_str = headers.get("content-length", "")

        if content_length_str:
            try:
                length = int(content_length_str)
            except ValueError:
                raise RequestsError(
                    f"Content-Length không hợp lệ: "
                    f"{content_length_str}"
                )

            if length == 0:
                return b""

            return self._read_bytes(length)

        return self._read_until_close()

    def _read_chunked_body(self) -> bytes:
        """Đọc body dạng chunked transfer encoding."""
        chunks = []

        while True:
            size_line = self._read_line()

            try:
                size_str = size_line.decode("ascii").split(";")[0]
                chunk_size = int(size_str.strip(), 16)
            except ValueError as exc:
                raise RequestsError(
                    f"Chunk size không hợp lệ: {exc}"
                )

            if chunk_size == 0:
                while True:
                    trailer = self._read_line()
                    if not trailer:
                        break
                break

            chunk_data = self._read_bytes(chunk_size)
            if chunk_data:
                chunks.append(chunk_data)

            self._read_line()

        return b"".join(chunks)

    def _read_until_close(self) -> bytes:
        """Đọc tới khi server đóng kết nối."""
        while self._recv_more():
            pass

        data = bytes(self._buf[self._offset:])
        self._offset = len(self._buf)
        return data
