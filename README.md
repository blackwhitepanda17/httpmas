# Tác giả : Nguyễn Tấn Dũng & MinhAnhs
 ## ``Form VietNamese``

[![PyPI version](https://img.shields.io/pypi/v/httpmas.svg)](https://pypi.org/project/httpmas/)
[![Python Version](https://img.shields.io/pypi/pyversions/httpmas.svg)](https://pypi.org/project/httpmas/)
[![Downloads](https://img.shields.io/pypi/dm/httpmas.svg)](https://pypi.org/project/httpmas/)
[![Contributors](https://img.shields.io/github/contributors/dmasntd/httpmas.svg)](https://github.com/dmasntd/httpmas/graphs/contributors)
[![Docs](https://img.shields.io/badge/docs-passing-brightgreen.svg)](https://github.com/dmasntd/httpmas)

## Sử dụng
 - Nó được thiết kết quen thuộc với đa số người dùng, các bạn có thể dùng theo ý muốn của mình
 - Nó cũng tương đồng như requests để không cảm thấy khó dùng
 
   ```python
   from httpmas import requests

   r = requests.get("https://example.com/")
   print(r.status_code, r.text)

   url = "https://example.com"
   r = requests.post(url, json={'key': 'val'})

   # Bất đồng bộ
   from httpmas import asyncio

   async def main():
    # Auto raise HTTPError khi server trả 4xx/5xx
    r = await asyncio.requests.get("https://httpbin.org/json")
    print(r.status_code, r.json())

    # Disable auto-raise
    r = await asyncio.requests.get(
        "https://httpbin.org/status/404",
        raise_on_error=False,
    )
    print(r.status_code)  # 404, không raise

   asyncio.run(main())

   ```

### Lưu ý 1 chút hiện trên github này chúng tôi chia sẻ là phiên bản đời thấp 2.9.18 dây là bản cũ chúng tôi chia sẻ để các bạn có thể hiểu cách chúng tôi hoạt động, vẫn lên ưu tiên cài ``pip install httpmas`` cách sử dụng của nó thật sự rất thuần requests

## Cài đặt
 - Hiện tại các bạn có thể cài bằng lệnh sau

   ```bash
   pip install httpmas

   httpmas --version <-- Lệnh kiểm tra phiên bản hiện tại

   httpmas --help <-- Lệnh xem cách dùng

   httpmas --info <-- Lệnh xem thông tin
   ```

### Phát triển bởi tôi
- Thư viện này được tôi "nấu" trên nền socket sẵn có
- Chúng tôi tận dùng socket để giảm tải các tầng nó đi qua tạo ra tốc độ nhanh chóng hơn
- Cũng một phần giải quyết tốc độ cho server của mình

## Báo cáo và thực tế
- Theo phân tích đến từ tác giả MinhAnhs chúng tôi đã so sánh tốc độ cho ra kết quả
  - Nhanh hơn ~3 lần so với requests
  - Nhanh hơn ~2 lần so với aiohttp
- Kết quả này chưa hoàn toàn chuẩn vì còn dựa trên một số yếu điểm thực tế, vả lại nó cũng đang trong giai đoạn phát triển
- Theo 1 số người dùng DEV họ cho thấy
  - Nhỉnh hơn requests 1,7 đến 2 lần
  - Nhỉnh hơn aiohttp 1,8 đến 2,1 
- Thắng aiohttp vì nó cũng chỉ dùng lượng requests bất đồng bộ nhỏ trong khi đó aiohttp thắng ở bất đồng bộ lượng lớn và nó có http2 hoặc thắng được thật(:>)
- Các bạn cũng có thể test và báo cáo tốc độ về cho chúng tôi biết để chúng tôi nâng cấp hơn

## Lưu ý
  - Môi trường mạng yếu cũng phải có mức độ nếu yếu quá chúng tôi cũng không thể hỗ trợ
  - Chúng tôi cần thời gian phát triển lên hiện tại chỉ có hỗ trợ http1.1
  - Chúng tôi cũng đang tập trung cho tốc độ và ổn định

# Nâng cấp và cập nhật tình trạng
 - Cập nhật lại xử lý nhanh hơn đôi chút, tốt trong môi trường mạng yếu
 - Xử lý lỗi logic lõi tăng cường tốc độ, sức mạnh chịu tải


# Liên hệ
- Bạn có thể yêu cầu tham gia dự án hoặc báo cáo hãy nhắn qua telegram @manhscuti

---

<p align="center">
  <img src="image.png" alt="Image" width="400">
</p>
