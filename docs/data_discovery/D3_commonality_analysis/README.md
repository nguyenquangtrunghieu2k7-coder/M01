# D3 – Cross-shop Commonality Analysis

**Trạng thái:** Phân tích khái niệm nghiệp vụ vòng 1.  
**Đầu vào:** D1 inventory + D2 classification + README và cấu trúc dữ liệu mẫu của 14 shop.  
**Mục tiêu:** Tìm phần lõi có thể chuẩn hóa mà không làm mất ngữ nghĩa riêng của từng shop.

> Quy ước bằng chứng: “Có” trong ma trận nghĩa là khái niệm được mô tả hoặc nhìn thấy trong cấu trúc nguồn; “Có thể có/Không rõ” nghĩa là chưa đủ bằng chứng để coi là field ổn định. Ma trận không phải thống kê null/non-null trên toàn bộ record.

## 1. Kết luận cốt lõi

**Không có một bảng Sales duy nhất nào mô tả đúng cả 14 shop.** Các shop có grain khác nhau:

- `sales_line`: một dòng hàng trong hóa đơn.
- `invoice`: một chứng từ tổng hợp, có thể không có dòng hàng.
- `payment_event`: một lần thu tiền/thanh toán.
- `inventory_event`: một biến động kho.
- `service_ticket`: một lượt sửa chữa/dịch vụ.
- `warranty_event`, `installment_event`, `trade_in_event`: các sự kiện vòng đời đặc thù.

Vì vậy, nên xây một mô hình chuẩn hóa dạng **event/document + optional line items + related events**, không ép mọi nguồn thành một bảng bán hàng phẳng.

## 2. Grain – quyết định quan trọng nhất

| Grain | Ý nghĩa | Ví dụ shop | Quy tắc |
|---|---|---|---|
| Document / Invoice | Một hóa đơn/đơn bán | dev_009, phần document của nhiều shop khác | Tổng tiền chứng từ chỉ lưu một lần ở grain này |
| Line item | Một mặt hàng/dịch vụ thuộc chứng từ | dev_001, 002, 005, 007, 008, 010, 011, 013, 014 | Thành tiền dòng được cộng ở grain dòng |
| Payment event | Một lần thu tiền | dev_003, dev_010; sổ phụ ở một số shop khác | Có thể nhiều payment cho một document |
| Inventory event | Một lần nhập/xuất/điều chỉnh kho | dev_003, 004, 005, 006 và nguồn phụ khác | Không suy ra từ sales nếu thiếu sự kiện kho |
| Service ticket | Một lượt sửa chữa | dev_012 | Công việc có thể nằm trong mô tả tự do; tổng tiền ở grain phiếu |
| Lifecycle event | Bảo hành, trả góp, thu máy cũ, trả hàng | dev_011, dev_014 và các shop có sổ phụ | Phải giữ event type riêng |

### Vì sao grain phải được xác định trước khi tính toán?

Ví dụ một hóa đơn có 3 dòng hàng và 2 lần thanh toán. Nếu join trực tiếp 3 dòng hàng với 2 lần thanh toán, kết quả có 6 dòng. Khi đó:
- Tổng tiền hàng có thể bị nhân đôi theo số lần thanh toán.
- Tổng tiền thanh toán có thể bị nhân đôi theo số dòng hàng.

Cách đúng: aggregate item lines về document và aggregate payments về document ở hai nhánh riêng, sau đó mới join kết quả đã tổng hợp.

## 3. Khái niệm chung và quyết định chuẩn hóa

| Khái niệm | Quyết định | Vì sao |
|---|---|---|
| Thời điểm sự kiện | Chuẩn hóa | Hầu hết dữ liệu nghiệp vụ đều có ngày; nhưng phải giữ loại ngày gốc |
| Loại sự kiện | Chuẩn hóa | Phân biệt bán hàng, thanh toán, trả hàng, nhập kho, sửa chữa, bảo hành... |
| Mã chứng từ/sự kiện | Chuẩn hóa có điều kiện | Có thể thiếu; một số sổ không có mã phiếu |
| Khách hàng/đối tác | Optional | Có khách lẻ, thiếu ID hoặc không ghi khách |
| Hàng hóa/dịch vụ | Optional, đa hình | Có shop không có item detail; dịch vụ có thể là text tự do |
| Số lượng/đơn vị | Optional | Chỉ có ý nghĩa với một số loại event/line |
| Đơn giá/thành tiền dòng | Optional | Không tồn tại trong invoice-summary hoặc ticket-total-only |
| Tổng tiền chứng từ | Optional theo loại event | Phải phân biệt tiền hàng, giảm giá, phí, phải trả, đã thu, còn nợ |
| Thanh toán | Event riêng | Một chứng từ có thể có nhiều lần thu |
| Điều chỉnh | Event/line có type | Voucher, điểm, phí ship, phí dịch vụ không cùng bản chất |
| Tồn kho/lô/IMEI | Extension theo domain | Không phải thuộc tính bắt buộc của mọi shop |
| Nguồn gốc dữ liệu | Bắt buộc trong pipeline | Cần audit và truy ngược kết quả chuẩn hóa |

Chi tiết mapping đề xuất nằm trong `common_business_concept_mapping.csv`.

## 4. Ma trận coverage theo shop

`shop_concept_coverage_matrix.csv` là bảng đối chiếu 14 shop theo các nhóm khái niệm:
- Ngày/thời điểm.
- Mã chứng từ/sự kiện.
- Chi tiết hàng hóa/dịch vụ.
- Số lượng.
- Số tiền.
- Khách hàng/đối tác.
- Thanh toán/công nợ.
- IMEI/serial.
- Bảo hành/dịch vụ.

Lưu ý: Đây là coverage định tính dựa trên cấu trúc và README, không phải tỷ lệ cột có dữ liệu sau khi quét toàn bộ bản ghi.

## 5. Những trường tuyệt đối không nên gộp một cách ngây thơ

### 5.1 Các trường tiền

Không dùng một cột `amount` chung mà không có `amount_type` và `grain`.

Tối thiểu cần phân biệt:
- `line_amount`: thành tiền một dòng hàng.
- `document_gross_amount`: tổng tiền hàng trước giảm.
- `document_discount_amount`: giảm giá cấp chứng từ.
- `charge_amount`: phí ship/phí dịch vụ/phụ phí.
- `document_payable_amount`: số tiền khách phải trả.
- `payment_amount`: tiền thực thu trong một lần thanh toán.
- `receivable_balance`: số dư còn phải thu tại một thời điểm.

### 5.2 Ngày tháng

Không gộp:
- Ngày bán/ngày hóa đơn.
- Ngày tạo đơn.
- Ngày giao hàng.
- Ngày thanh toán.
- Ngày nhập kho.
- Ngày bảo hành/sửa chữa.

Canonical event có thể dùng `event_timestamp`, nhưng cần giữ `source_date_field` và `event_type`.

### 5.3 Mã định danh

- Mã đơn không nhất thiết là mã thanh toán.
- IMEI định danh thiết bị, không định danh toàn bộ đơn hàng.
- Tên khách không phải customer key đáng tin cậy.
- Tên sản phẩm không phải product key ổn định.
- Một số sổ không có ticket ID; không tự bịa mã nguồn.

## 6. Canonical model đề xuất – bản khái niệm

```text
SourceRecord
  ├── provenance
  │    ├── source_shop_id
  │    ├── source_file
  │    ├── source_object (sheet/table)
  │    ├── source_row
  │    └── adapter_version
  │
  └── BusinessEvent
       ├── event_id (internal surrogate, not source ID)
       ├── source_event_id (nullable)
       ├── event_type
       ├── event_timestamp
       ├── party_ref (nullable)
       ├── document_ref (nullable)
       ├── amount_components (typed, nullable)
       ├── line_items (0..N)
       │    ├── item_ref (nullable)
       │    ├── item_type
       │    ├── description_raw
       │    ├── quantity (nullable)
       │    ├── unit_raw (nullable)
       │    ├── unit_price (nullable)
       │    └── line_amount (nullable)
       └── related_events (0..N)
            ├── payment
            ├── return/refund
            ├── inventory movement
            ├── warranty/service
            ├── installment/debt
            └── trade-in
```

Đây là mô hình khái niệm, chưa phải schema vật lý cuối cùng. Không phải mọi event đều có document, party hoặc line items.

## 7. Hàm ý thiết kế Generic Profiler

Profiler không chỉ cần kiểm tra `dtype`, `null_count`, `unique_count`. Nó cần phát hiện dấu hiệu ngữ nghĩa:

1. **Candidate grain:** một dòng có vẻ là document, line item, payment, ticket hay inventory event?
2. **Repeated document attributes:** trường tổng tiền/khách/ngày có lặp theo mã đơn không?
3. **Candidate keys:** mã đơn, mã hàng, IMEI, mã thanh toán có unique ở đúng grain không?
4. **Relationship cardinality:** một đơn có bao nhiêu dòng hàng? bao nhiêu payment? một IMEI liên quan bao nhiêu event?
5. **Amount semantics:** cột tiền có phải tiền dòng, tiền đơn hay tiền thanh toán?
6. **Mixed row types:** có dòng voucher/ship/điểm nằm trong bảng item không?
7. **Temporal semantics:** ngày có nhiều định dạng hay nhiều loại ngày không?
8. **Unit semantics:** có nhiều đơn vị và bảng quy đổi không?
9. **Source provenance:** mọi kết quả đều truy ngược được về nguồn gốc.

## 8. Những điểm cần kiểm chứng trước khi chốt D4

- Quét toàn bộ header của tất cả sheet/table và phát hiện header nhiều dòng.
- Đo null/duplicate/unique trên các candidate key.
- So sánh schema theo tháng ở dev_002 và các shop có file tháng.
- Định lượng số hóa đơn có nhiều dòng, số đơn có nhiều payment.
- Kiểm tra quan hệ join và orphan records.
- Kiểm tra các cột tiền bằng đối soát ở từng shop, không chỉ dev_001.
- Kiểm tra số lượng âm, dòng điều chỉnh và các dòng không phải hàng hóa.

**Kết luận D3:** Phần lõi nên là một mô hình sự kiện/chứng từ có các thành phần tùy chọn và các event liên quan. Adapter chịu trách nhiệm giữ đúng grain và ngữ nghĩa của từng shop; Generic Profiler phát hiện cấu trúc và rủi ro; canonical model không được làm mất dữ liệu đặc thù.
