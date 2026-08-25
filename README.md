# Tác giả : Nguyễn Tấn Dũng & MinhAnhs
 ## Form VietNamese

## Tôi ở đây mang đến một giải pháp mới thay thế cho requests ở python
 - Theo phân tích đến từ tác giả MinhAnhs chúng tôi đã so sánh tốc độ cho ra kết quả
 - Nhanh hơn gấp 3 lần so với requests
 - Nhanh hơn gấp 1 lần so với aiohttp
 - Kết quả này chưa hoàn toàn chuẩn vì còn dựa trên một số yếu điểm thực tế, vả lại nó cũng đang trong giai đoạn phát triển
 - Thắng aiohttp vì nó cũng chỉ dùng lượng requests bất đồng bộ nhỏ trong khi đó aiohttp thắng ở bất đồng bộ lượng lớn và nó có http2 :>


# Cài đặt
 - Hiện tại chúng tôi đang phát triển nội bộ bạn có thể cài thủ công để dùng
 - Tuy nhiên chúng tôi chưa tối ưu lắm lên cần thời gian và cộng đồng hỗ trợ bạn có thể báo cáo về địa chỉ telegram @tdungdepzai

# Sử dụng
 - Nó được thiết kết quen thuộc với đa số người dùng

   ```python
   form httpmas import requests

   r = requests.get("https://example.com/")
   print(r.status_code, r.text)

   #Tùy vào cách các bạn dùng
   
   ```
