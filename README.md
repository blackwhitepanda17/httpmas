# Tác giả : Nguyễn Tấn Dũng & MinhAnhs
 ## ``Form VietNamese``

[![PyPI version](https://img.shields.io/pypi/v/httpmas.svg)](https://pypi.org/project/httpmas/)
[![Python Version](https://img.shields.io/pypi/pyversions/httpmas.svg)](https://pypi.org/project/httpmas/)
[![Downloads](https://img.shields.io/pypi/dm/httpmas.svg)](https://pypi.org/project/httpmas/)
[![Contributors](https://img.shields.io/github/contributors/dmasntd/httpmas.svg)](https://github.com/dmasntd/httpmas/graphs/contributors)
[![Docs](https://img.shields.io/badge/docs-passing-brightgreen.svg)](https://github.com/dmasntd/httpmas)

## Sử dụng
 - Nó được thiết kết quen thuộc với đa số người dùng, các bạn có thể dùng theo ý muốn
 
   ```python
   form httpmas import requests

   r = requests.get("https://example.com/")
   print(r.status_code, r.text)

   url = "https://example.com"
   r = requests.port(url, json={'key': 'val'})
   ```

## Cài đặt
 - Hiện tại các bạn có thể cài bằng lệnh sau

   ```bash
   pip install httpmas
   
   # Kiểm tra bằng lệnh
  
   httpmas --version
  
   # Cần hỗ trợ
  
   httpmas --help
   
   # Cần xem thông tin

   httpmas --info
   ```

### Phát triển bởi PyMaKaizu
- Thư viện này thuộc bản quyền của chúng tôi, chúng tôi cũng là tác giả của PyMaKaizu
- Thư viện này được tôi sử dụng trong PyMaKaizu để giải quyết vấn đề tốc độ kết nối đến server của mình
- Vì nếu giữ nội bộ chúng tôi phải nghĩ thêm giải pháp cho nó, chúng tôi lười lên chia sẻ lên pypi để tiện lợi hơn
- Cơ bản là lười và cũng chẳng muốn cồng kềnh để xử lý thêm mã nguồn này
- Hiện tại bản chia sẻ này các bạn có thể tải về để nâng cấp và không mạnh bằng việc cài qua pip vì chúng tôi lười cập nhật trên github

## Chúng tôi ở đây mang đến một giải pháp mới thay thế cho requests ở python
- Chúng tôi "nấu" trên socket để giảm bớt các tầng nó phải đi qua

## Báo cáo và thực tế
- Theo phân tích đến từ tác giả MinhAnhs chúng tôi đã so sánh tốc độ cho ra kết quả
  - Nhanh hơn ~3 lần so với requests
  - Nhanh hơn ~2 lần so với aiohttp
- Kết quả này chưa hoàn toàn chuẩn vì còn dựa trên một số yếu điểm thực tế, vả lại nó cũng đang trong giai đoạn phát triển
- Theo 1 số người dùng DEV họ cho thấy
  - Nhỉnh hơn requests 1,7 đến 2 lần
  - Nhỉnh hơn aiohttp 1,8 đến 2,1 
- Thắng aiohttp vì nó cũng chỉ dùng lượng requests bất đồng bộ nhỏ trong khi đó aiohttp thắng ở bất đồng bộ lượng lớn và nó có http2 (:>)
- Các bạn cũng có thể test và báo cáo tốc độ về cho chúng tôi biết để chúng tôi nâng cấp hơn


## Lưu ý
  - Môi trường mạng yếu cũng phải có mức độ nếu yếu quá chúng tôi cũng không thể hỗ trợ
  - Chúng tôi cần thời gian phát triển lên hiện tại chỉ có hỗ trợ http1.1
  - Có lẽ phần mã nguồn chúng tôi sẽ độc quyền hoặc không
  - Tác giả cũng cần thời gian nâng cấp không thể đùng cái xịn ngay
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
