# M03 — Semantic Layer + Query Planning

## Mục tiêu

Chuyển ý định câu hỏi thành cách tính đúng nghiệp vụ và kế hoạch truy vấn có thể kiểm tra được.

## Đầu vào

`QuestionIntent` từ M02, `BusinessCatalog` từ M01, rulebook, README, lịch âm dương và thư viện định nghĩa chỉ số.

## Xử lý chính

1. Chọn chỉ số và đối tượng đúng nghĩa của câu hỏi.
2. Áp luật chung và luật ngành; xác định trạng thái, đơn vị và nguồn dữ liệu cần dùng.
3. Chuyển ý định thời gian thành khoảng ngày hoặc mốc cuối ngày cụ thể bằng code.
4. Kiểm tra nguồn có đủ dữ liệu, quan hệ và phạm vi thời gian để trả lời hay không.
5. Lập `QueryPlan`, rồi biên dịch thành SQL có tham số hoặc lời gọi hàm nghiệp vụ được cho phép.

Mỗi chỉ số có một `MetricSpec` chứa ý nghĩa, cách gọi, công thức, cấp dữ liệu tính toán, bộ lọc, trường thời gian, đơn vị, quan hệ nối bảng và yêu cầu dữ liệu. Model đề xuất lựa chọn chỉ số và tham số; code kiểm tra và biên dịch kế hoạch.

## Các luật kiến trúc phải bảo toàn

| Chủ đề | Nguyên tắc |
| --- | --- |
| Doanh thu | Cộng thành tiền dòng sau giảm giá dòng; loại cả đơn huỷ hoặc có trả hàng, kể cả trả một phần; vẫn tính đơn đang giao; không trừ giảm giá cả đơn, không cộng VAT hoặc phí ship |
| Trạng thái trả hàng | Xác định ở cấp đơn từ các nguồn liên quan trước khi lọc kỳ doanh thu; giữ ngoại lệ trả sau kỳ hoặc sau hôm nay theo rulebook |
| Đếm và xếp hạng | Phân biệt số đơn, số dòng, tổng lượng và số ngày; bán chạy dùng lượng quy về đơn vị cơ bản |
| Công nợ | Dùng số phải trả và các khoản thanh toán đến mốc hỏi; loại COD/sàn TMĐT; đơn trả hàng còn nợ vẫn có thể được tính |
| Kho và giá vốn | Tồn kho theo sự kiện/snapshot vật lý; lãi gộp dùng giá vốn trên dòng bán; giá trị tồn chung và giá trị lô có cơ sở định giá khác nhau |
| Nối bảng | Tính ở đúng cấp đơn/dòng/phiếu; tổng hợp các bảng nhiều dòng về cùng cấp trước khi nối để tránh nhân tổng |
| Luật ngành | Tách topping, voucher, điểm, giao nhiều đợt, lượt sửa, bảo hành, thu máy cũ và trả góp theo đúng ngành |

Yêu cầu rõ của câu hỏi được ưu tiên trong phạm vi luật bài toán; tiếp theo là luật ngành và luật chung. README mô tả cách ghi, ý nghĩa cột, quy đổi và phạm vi dữ liệu. Mâu thuẫn chưa giải được phải được ghi nhận thay vì tự chọn công thức.

## Xử lý thời gian và dữ liệu thiếu

- “Hôm nay” luôn là `as_of_date`; xử lý ngày giờ theo GMT+7 và ý nghĩa của nguồn.
- Tuần bắt đầu thứ Hai. “Tháng này”, kỳ so sánh, tháng/quý thiếu năm và N ngày gần nhất theo rulebook; dịp Tết tra `calendar.csv`.
- Khoảng bao gồm hai đầu được chuyển thành `[start, end_exclusive)` khi lọc timestamp.
- Phân biệt phát sinh trong kỳ với tình trạng tích lũy đến cuối ngày. Snapshot cuối kỳ chỉ dùng cho mốc khác khi có lịch sử đủ để dựng lại.
- Kỳ hoàn toàn ngoài phạm vi dữ liệu là `unanswerable`; kỳ giao một phần được tính trên phần có dữ liệu. Thiếu dữ liệu khác với không phát sinh và bằng 0.
- Capability được xác định theo chỉ số và nguồn. Nguồn chỉ có tổng hóa đơn có thể hỗ trợ doanh thu toàn shop nhưng không hỗ trợ doanh thu theo sản phẩm.

## Đầu ra bàn giao

`QueryPlan` được xác thực gồm chỉ số, thực thể, điều kiện, khoảng ngày, bảng/hàm sử dụng, cách nhóm và xếp hạng, đơn vị, kiểu đáp án và yêu cầu kiểm chứng. Kèm SQL có tham số hoặc lời gọi hàm để M04 thực thi.

Nếu đã xác nhận thiếu dữ liệu, M03 tạo quyết định `unanswerable`. Nếu còn mơ hồ hoặc chưa xác minh được mapping/kế hoạch, tạo `abstain`. Hai trạng thái này được gửi tới M05 mà không cần chạy truy vấn.

## Ranh giới trách nhiệm

M03 sở hữu định nghĩa nghiệp vụ và cách lập truy vấn; M04 sở hữu quyền thực thi và kiểm chứng kết quả. Đường chính dùng công thức, compiler và hàm đã định nghĩa. SQL do model sinh trực tiếp là đường dự phòng khi dữ liệu đủ nhưng chưa có template phù hợp, và vẫn phải qua đầy đủ kiểm tra.