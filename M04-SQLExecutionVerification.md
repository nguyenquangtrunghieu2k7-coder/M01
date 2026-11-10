
# M04 — SQL Execution + Verification

## Mục tiêu

Thực thi kế hoạch trên dữ liệu thật và xác nhận kết quả phù hợp với yêu cầu. SQL chạy thành công chưa đủ để coi đáp án là đúng.

## Đầu vào

`QueryPlan`, SQL/hàm được đề xuất từ M03, kho chuẩn hóa từ M01 và yêu cầu kiểm chứng đi kèm.

## Xử lý chính

1. Kiểm tra cấu trúc truy vấn, bảng/cột/hàm được phép và phạm vi shop trước khi chạy.
2. Chạy trong worker có giới hạn thời gian, bộ nhớ và quyền truy cập.
3. Kiểm tra cấp dữ liệu, quan hệ nối bảng, khoảng ngày, trạng thái, đơn vị, mẫu số, null bắt buộc và số lượng kết quả.
4. Kiểm tra cách xếp hạng, dấu tăng/giảm, thứ tự phần tử và thứ tự cột theo kế hoạch.
5. Gắn kết quả với nguồn và phép kiểm tra. Lỗi sửa được gửi lại M03 trong ngân sách cho phép; không sửa được thì bỏ qua.

## Đầu ra bàn giao

`ExecutionResult` gồm giá trị tính toán giữ nguyên độ chính xác cần thiết, đơn vị, cấu trúc kết quả, nguồn tham chiếu, kết quả kiểm chứng và trạng thái. Chỉ kết quả vượt qua kiểm tra mới được đánh dấu sẵn sàng xuất đáp án. M05 thực hiện làm tròn cuối cùng.

## Ranh giới trách nhiệm

- Kết nối truy vấn chỉ đọc; tách quyền đọc nguồn ở M01 khỏi quyền truy vấn ở M04.
- Chỉ cho phép truy vấn `SELECT`/`WITH … SELECT` đã kiểm tra cả truy vấn con, hàm và bảng. Chặn đọc/ghi file, network, `ATTACH`, `COPY`, tải extension và thay cấu hình ngoài phạm vi cho phép.
- Read-only database không tự ngăn mọi khả năng đọc file của engine. Kết hợp giới hạn engine, worker và môi trường chạy; xem [hướng dẫn bảo vệ DuckDB](https://duckdb.org/docs/preview/operations_manual/securing_duckdb/overview).
- Chỉ gọi hàm Python đã được triển khai và kiểm thử; baseline không thực thi Python tùy ý do model sinh.
- Sửa kế hoạch/truy vấn tối đa hai lần trong deadline câu hỏi. Mọi bản sửa phải được kiểm tra lại trước khi chạy.
- Không cắt danh sách/bảng được hỏi đầy đủ rồi coi kết quả cắt là đáp án hoàn chỉnh. Top-k có ít hơn k ứng viên thì giữ toàn bộ ứng viên hợp lệ.
- Timeout, lỗi đọc nguồn hoặc lỗi SQL không tự chứng minh thiếu dữ liệu. Nếu chưa khắc phục được, dùng `abstain`.
