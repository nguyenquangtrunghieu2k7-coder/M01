
# M01 — Data Processing

## Mục tiêu

Biến file thô của shop thành dữ liệu có cấu trúc thống nhất, biết rõ mỗi dòng đại diện cho điều gì, có thể truy vấn và truy ngược về nguồn.

## Đầu vào

File Excel/CSV/SQLite của một shop, README mô tả nguồn và cấu hình đọc dữ liệu đã được kiểm tra.

## Xử lý chính

1. Khám phá file, sheet, bảng, vị trí header, tên cột và quan hệ khóa.
2. Đọc dữ liệu; chuẩn hóa ngày, giờ, tiền, tên gọi, trạng thái và đơn vị.
3. Tách các thực thể nghiệp vụ như đơn hàng, dòng hàng, thanh toán, lượt sửa xe và sự kiện kho.
4. Kiểm tra mapping, khóa, dòng trùng và tính nhất quán; ghi lại lỗi có vị trí nguồn.
5. Lưu kho chuẩn hóa và danh mục dữ liệu của shop.

Kho có ba tầng logic: **raw** giữ nguồn nguyên trạng, **staging** chứa giá trị gốc cùng kết quả parse, **mart** chứa các bảng nghiệp vụ để truy vấn. Không cần triển khai ba hệ thống lưu trữ riêng.

## Mô hình dữ liệu ở mức tổng thể

| Nhóm bảng | Mỗi dòng đại diện cho |
| --- | --- |
| `orders`, `order_lines`, `order_adjustments` | Một đơn, một dòng hàng hoặc một khoản điều chỉnh |
| `products`, `customers`, `entity_aliases`, `unit_conversions` | Một thực thể, một cách gọi hoặc một quan hệ quy đổi |
| `payments`, `purchase_receipts`, `purchase_lines`, `returns` | Một lần thanh toán, phiếu nhập, dòng nhập hoặc sự kiện trả hàng |
| `inventory_events`, `inventory_snapshots`, `lots`, `lot_allocations` | Một biến động, số dư tại mốc xác định, lô hàng hoặc phân bổ theo lô |
| `price_history`, `expenses`, `deliveries` | Một lần đổi giá, khoản chi hoặc dòng hàng của một đợt giao |
| `service_visits`, `visit_tasks` | Một lượt sửa xe hoặc một công việc trong lượt sửa |
| `trade_ins`, `installment_schedules`, `warranty_visits` | Một lần thu máy cũ, kỳ góp hoặc lượt bảo hành |
| `source_lineage` | Một quan hệ giữa record chuẩn hóa và file/sheet/dòng/ô nguồn |

Chỉ tạo những bảng và trường mà shop có nguồn hỗ trợ. Khóa được đặt trong phạm vi shop và bổ sung phạm vi file/kỳ khi mã nguồn bị tái sử dụng.

## Đầu ra bàn giao

`BusinessDataset` gồm kho chuẩn hóa, phiên bản dữ liệu và `BusinessCatalog`. Catalog mô tả bảng/cột, khóa nối, cách gọi thực thể, quy đổi đơn vị, phạm vi ngày, mốc snapshot và khả năng trả lời từng nhóm chỉ số. Mỗi dữ kiện hoặc phép biến đổi có thông tin truy vết nguồn.

## Ranh giới trách nhiệm

M01 xác định dữ liệu được ghi như thế nào. M03 quyết định phải dùng dữ liệu đó để tính chỉ số nào và theo luật nào. LLM có thể đề xuất mapping cột, nhưng mapping phải vượt qua kiểm tra trước khi sử dụng.

Các nguyên tắc cần giữ:

- Tiêu đề nhiều dòng, ô gộp và dữ liệu chia nhiều sheet/file phải được xử lý theo cấu trúc thực tế.
- Ô trống chỉ được kế thừa trong đúng nhóm đơn/phiếu. Không forward-fill toàn sheet.
- Tiền của cả đơn lặp trên nhiều dòng hàng chỉ được ghi nhận một lần ở cấp đơn.
- Chỉ loại dòng trùng theo quy tắc của nguồn. Với sổ không ghi theo đơn, hai dòng giống nhau vẫn có thể là hai lần phát sinh hợp lệ.
- Quy đổi đơn vị theo sản phẩm và shop, kể cả nhiều tầng; không mặc định mọi “thùng” có cùng hệ số.
- Giữ nguyên tên hiển thị; chuẩn hóa hoặc bỏ dấu phục vụ tìm kiếm không làm đổi định danh khách/sản phẩm.
- Không thực thi macro hoặc mã trong nguồn. Công thức Excel thiếu cached value cần cách tính được hỗ trợ hoặc lỗi chất lượng, không được xem như 0.
- Snapshot nợ/tồn cuối kỳ phải có ngày hiệu lực; không tự tạo lịch sử từ một số dư cuối kỳ.