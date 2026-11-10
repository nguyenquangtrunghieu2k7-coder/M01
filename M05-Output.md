
# M05 — Output

## Mục tiêu

Chuyển kết quả đã kiểm chứng hoặc quyết định xử lý thành record JSONL đúng chuẩn chấm điểm.

## Đầu vào

`ExecutionResult` từ M04 hoặc quyết định xử lý sớm từ M03/bộ điều phối, kèm ngữ cảnh câu hỏi gốc và quy tắc kiểu đáp án đã được xác nhận.

## Xử lý chính

1. Kiểm tra trạng thái trả lời và kiểu đáp án.
2. Làm tròn ở bước cuối, giữ đúng đơn vị, tên hiển thị, thứ tự danh sách và cột bảng.
3. Serialize bằng code, không dùng thêm lượt sinh văn bản để viết lại con số.
4. Kiểm tra mỗi `id` xuất hiện đúng một lần và đầu ra đủ tập ID đầu vào.
5. Ghi UTF-8 JSONL; lưu trace riêng, không trộn giải thích hoặc SQL vào đáp án.

## Ba kết quả xử lý

| Kết quả | Khi sử dụng |
| --- | --- |
| Đáp án | Nguồn phù hợp, tính được và vượt qua kiểm chứng |
| `unanswerable` | Xác nhận dữ liệu nguồn không đủ để trả lời hoặc kỳ hoàn toàn ngoài phạm vi |
| `abstain` | Hệ thống chưa hiểu, chưa tính hoặc chưa kiểm chứng được chắc chắn |

Theo rulebook, đáp án đúng được +1, sai −1, bỏ qua 0. `unanswerable` cũng là dự đoán được chấm điểm. Không dùng nó thay cho lỗi hệ thống. Confidence tự khai của model không thay thế được điều kiện kiểm chứng.

## Đầu ra bàn giao

`SubmissionRecord` được ghi vào `submission.jsonl` theo schema của rulebook:

| `type` | Giá trị `answer` |
| --- | --- |
| `number` | JSON number, tiền là số nguyên VND; không đơn vị hoặc dấu phân cách nghìn |
| `percent` | JSON number theo đơn vị phần trăm: 12,4% ghi `12.4` |
| `date` | Chuỗi `YYYY-MM-DD`, hoặc `YYYY-MM` nếu hỏi theo tháng |
| `boolean` | JSON boolean `true` hoặc `false` |
| `string` | Chuỗi theo tên/giá trị trong nguồn, giữ dấu tiếng Việt |
| `list` | Mảng JSON đúng thứ tự; một phần tử vẫn là mảng |
| `table` | Object có `columns` và `rows`; cột đầu là thực thể, cột sau theo thứ tự câu hỏi |
| `unanswerable` | Không cần `answer`; `reason` nếu có phải là chuỗi |
| `abstain` | Không cần `answer` |

## Ranh giới trách nhiệm

M05 giữ nguyên ý nghĩa của kết quả, không đổi công thức hay bổ sung dữ kiện. Tiền lưu và tính bằng integer/decimal phù hợp; giữ tử số và mẫu số khi cần. Làm tròn tiền về đồng và tỷ lệ/trung bình theo rulebook, không làm tròn các thành phần trước khi cộng. Chặn NaN/Infinity, không biến số thành chuỗi có đơn vị.

Phép chia decimal của DuckDB có thể trả floating-point; cần kiểm soát độ chính xác và làm tròn cuối bằng code, theo [tài liệu kiểu số DuckDB](https://duckdb.org/docs/current/sql/data_types/numeric). Mẫu số 0 không tự biến thành tỷ lệ 0 khi chưa có quy tắc xác nhận.
