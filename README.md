# Tác giả : Nguyễn Tấn Dũng & MinhAnhs
 ## Form VietNamese

### Phát triển bởi PyMaKaizu
- Thư viện này thuộc bản quyền của chúng tôi, chúng tôi cũng là tác giả của PyMaKaizu
- Thư viện này được tôi sử dụng trong PyMaKaizu để giải quyết vấn đề tốc độ kết nối đến server
- Vì nếu giữ nội bộ chúng tôi phải nghĩ thêm giải pháp cho nó, chúng tôi lười lên chia sẻ lên pipy để tiện lợi hơn
- Cơ bản là lười và cũng chẳng muốn cồng kềnh

## Chúng tôi ở đây mang đến một giải pháp mới thay thế cho requests ở python
 - Chúng tôi phát triển và tối ưu nó để hoạt động ở môi trường wifi, mạng dữ liệu kém, chập chờn tốt hơn
 - Kết nối nhanh hơn tăng tốc trong giao thức và giao tiếp giữa người dùng (client) và máy chủ (server)
 - Bảo mật hơn với TLS 1.3 (thực tế không cần vì sẵn có trong mọi môi trường nhưng chúng tôi vẫn ưu tiên làm)
 - Chúng tôi cũng có 1 thư viện mang tên Dmas nhưng không lạ gì khi nó không được chia sẻ vì sản phẩm nội bộ

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

## Sử dụng
 - Nó được thiết kết quen thuộc với đa số người dùng, các bạn có thể dùng theo ý muốn

   ```python
   form httpmas import requests

   r = requests.get("https://example.com/")
   print(r.status_code, r.text)

   #Tùy vào cách các bạn dùng
   
   ```

   ```python
   form httpmas import requests
   
   url = "https://example.com"
   r = requests.port(url, json={'key': 'val'})
   ```

## Lưu ý
  - Môi trường mạng yếu cũng phải có mức độ nếu yếu quá chúng tôi cũng không thể hỗ trợ
  - Chúng tôi cần thời gian phát triển lên hiện tại chỉ có hỗ trợ http1.1
  - Hiện tại chưa đưa lên pipy vì đang test nội bộ
  - Có lẽ phần mã nguồn chúng tôi sẽ độc quyền hoặc không
  - Tốc độ hiện tại cũng nhanh nhưng vẫn thủ dâm tinh thần vì test không đem lại thực tế
  - Tác giả cũng cần thời gian nâng cấp không thể đùng cái xịn ngay
  - Chúng tôi cũng đang tập trung cho tốc độ và ổn định

# Nâng cấp
 - Hiện tại chúng tôi đang phát triển lên http/2 và nâng cao tốc độ xử lý hơn
 - Cập nhật lại xử lý nhanh hơn đôi chút, tốt trong môi trường mạng yếu

