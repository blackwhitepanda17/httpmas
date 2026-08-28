"""
Đối tượng Response của httpmas.
Đóng gói toàn bộ thông tin phản hồi HTTP.
"""

import json as _json
from typing import Any, Dict, Optional

from .exceptions import RequestsError


class Response:
    """Đối tượng phản hồi HTTP.

    Thuộc tính:
        status_code: Mã trạng thái HTTP.
        reason: Lý do (ví dụ: "OK", "Not Found").
        headers: Từ điển headers phản hồi.
        content: Body dạng byte thô.
        url: URL đã request.
        encoding: Mã hóa ký tự được phát hiện.
        elapsed: Thời gian xử lý request (giây).
    """

    def __init__(
        self, status_code: int, reason: str,
        headers: Dict[str, str], content: bytes,
        url: str, elapsed: float = 0.0
    ) -> None:
        """Khởi tạo Response.

        Tham số:
            status_code: Mã trạng thái HTTP.
            reason: Chuỗi lý do.
            headers: Từ điển headers.
            content: Body byte.
            url: URL gốc.
            elapsed: Thời gian thực thi (giây).
        """
        self.status_code = status_code
        self.reason = reason
        self.headers = headers
        self.content = content
        self.url = url
        self.elapsed = elapsed
        self.encoding: Optional[str] = None

    @property
    def ok(self) -> bool:
        """Kiểm tra response có thành công không (status < 400)."""
        return self.status_code < 400

    @property
    def text(self) -> str:
        """Trả về body dạng chuỗi Unicode.

        Tự động phát hiện encoding từ header Content-Type.
        """
        encoding = self._detect_encoding()
        try:
            return self.content.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            return self.content.decode("utf-8", errors="replace")

    def _detect_encoding(self) -> str:
        """Phát hiện encoding từ header hoặc mặc định UTF-8.

        Trả về:
            Tên encoding.
        """
        if self.encoding:
            return self.encoding

        content_type = self.headers.get("content-type", "")
        if "charset=" in content_type:
            parts = content_type.split("charset=")
            if len(parts) > 1:
                charset = parts[1].split(";")[0].strip().strip("'\"")
                if charset:
                    return charset

        return "utf-8"

    def json(self) -> Any:
        """Phân tích body thành đối tượng Python (dict/list).

        Trả về:
            Dữ liệu đã phân tích JSON.

        Ngoại lệ:
            RequestsError: Nếu body không phải JSON hợp lệ.
        """
        try:
            return _json.loads(self.text)
        except _json.JSONDecodeError as exc:
            raise RequestsError(f"Không thể phân tích JSON: {exc}")

    def raise_for_status(self) -> None:
        """Ném RequestsError nếu status code là lỗi (4xx hoặc 5xx).

        Ngoại lệ:
            RequestsError: Khi status code >= 400.
        """
        if 400 <= self.status_code < 600:
            raise RequestsError(
                f"HTTP {self.status_code} {self.reason}"
            )

    def __repr__(self) -> str:
        """Biểu diễn chuỗi của Response."""
        return f"<Response [{self.status_code} {self.reason}]>"