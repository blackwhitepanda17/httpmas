# Tác giả : Nguyễn Tấn Dũng & MinhAnhs
 ## Form VietNamese

### Phát triển bởi PyMaKaizu
- Thư viện này thuộc bản quyền của chúng tôi, chúng tôi cũng là tác giả của PyMaKaizu
- Thư viện này được tôi sử dụng trong PyMaKaizu để giải quyết vấn đề tốc độ kết nối đến server
- Vì nếu giữ nội bộ chúng tôi phải nghĩ thêm giải pháp cho nó, chúng tôi lười lên chia sẻ lên pipy để tiện lợi hơn
- Cơ bản là lười và cũng chẳng muốn cồng kềnh

## Tôi ở đây mang đến một giải pháp mới thay thế cho requests ở python
 - Theo phân tích đến từ tác giả MinhAnhs chúng tôi đã so sánh tốc độ cho ra kết quả
 - Nhanh hơn gấp 3 lần so với requests
 - Nhanh hơn gấp 1 lần so với aiohttp
 - Kết quả này chưa hoàn toàn chuẩn vì còn dựa trên một số yếu điểm thực tế, vả lại nó cũng đang trong giai đoạn phát triển
 - Thắng aiohttp vì nó cũng chỉ dùng lượng requests bất đồng bộ nhỏ trong khi đó aiohttp thắng ở bất đồng bộ lượng lớn và nó có http2 (:>)


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

## Lưu ý
  - Chúng tôi cần thời gian phát triển lên hiện tại chỉ có hỗ trợ http1.1
  - Hiện tại chưa đưa lên pipy vì đang test nội bộ
  - Có lẽ phần mã nguồn chúng tôi sẽ độc quyền hoặc không
  - Tốc độ hiện tại cũng nhanh nhưng vẫn thủ dâm tinh thần vì test không đem lại thực tế
  - Tác giả cũng cần thời gian nâng cấp không thể đùng cái xịn ngay
  - Chúng tôi cũng đang tập trung cho tốc độ và ổn định
