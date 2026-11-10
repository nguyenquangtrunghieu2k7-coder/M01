
# M02 — Question Understanding

## Mục tiêu

Hiểu người hỏi muốn biết điều gì, nói tới đối tượng nào và dùng biểu thức thời gian nào, kể cả cách viết tắt, không dấu hoặc tiếng Việt đời thường.

## Đầu vào

Câu hỏi gốc cùng `id`, `business_id`, `as_of_date`; danh mục bảng, thực thể và cách gọi liên quan từ M01.

## Xử lý chính

1. Chuẩn hóa cách diễn đạt để phân tích, đồng thời giữ nguyên câu hỏi gốc.
2. Nhận diện yêu cầu: tính tổng, đếm, xếp hạng, so sánh, lọc, liệt kê hoặc hỏi trạng thái tại một ngày.
3. Trích xuất đối tượng, điều kiện, nhóm cần phân tích, số lượng top-k và thứ tự kết quả mong muốn.
4. Nhận diện ý định thời gian như “tháng trước”, “7 ngày gần nhất” hoặc “đến hết hôm nay”.
5. Ghi nhận những cách hiểu còn mơ hồ để M03 kiểm tra theo luật và dữ liệu.

## Đầu ra bàn giao

`QuestionIntent`: mô tả yêu cầu có cấu trúc, gồm câu hỏi gốc, loại phép hỏi, thực thể ứng viên, điều kiện, biểu thức thời gian và kiểu đáp án dự kiến. Ngữ cảnh nhận diện câu hỏi phải khớp đầu vào.

## Ranh giới trách nhiệm

M02 xác định **ý định**. M03 chốt định danh thực thể, công thức nghiệp vụ, khoảng ngày chính xác và kiểu đáp án. Ví dụ M02 nhận ra “tháng trước”; code thời gian của M03 mới tính ngày bắt đầu và kết thúc từ `as_of_date`.

M02 không tự cộng số liệu, không dựng SQL hoàn chỉnh và không kết luận dữ liệu thiếu chỉ vì chưa hiểu câu hỏi. Không đưa toàn bộ giao dịch vào prompt; chỉ cung cấp ngữ cảnh của đúng shop và những mục liên quan.
