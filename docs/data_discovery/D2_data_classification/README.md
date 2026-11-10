# D2 – Phân loại cấu trúc dữ liệu 14 shop

**Trạng thái:** Phân loại vòng 1 dựa trên `README.md` của cả 14 shop và inventory D1.  
**Phạm vi:** Mô hình bản ghi, cách chia file/bảng, khóa liên kết, quy tắc nghiệp vụ và rủi ro chuẩn hóa.  
**Chưa phải:** Data contract cuối cùng hoặc kết quả profiling định lượng trên mọi cột/dòng.

## 1. Kết luận chính

14 shop không có một schema đồng nhất. Có thể nhận diện một số họ cấu trúc để xây dựng adapter dùng chung, nhưng không nên tạo một adapter riêng cho từng định dạng file đơn thuần.

Các chiều phân loại quan trọng:

1. **Record grain – một dòng đại diện cho điều gì?** Một dòng hàng, một hóa đơn, một phiếu sửa chữa, một lần thanh toán hay một sự kiện kho.
2. **Physical organization – dữ liệu được lưu thế nào?** Một bảng, nhiều file theo tháng/năm, nhiều sheet, nhiều bảng quan hệ, hay database.
3. **Linkage – các phần dữ liệu nối với nhau bằng gì?** ID ổn định, mã đơn, SKU, IMEI, tên hàng, tên khách, số thứ tự sổ, hoặc không có khóa.
4. **Business semantics – quy tắc nghiệp vụ đặc biệt?** Giảm giá cấp dòng/đơn, công nợ, trả hàng, phí ship, phí dịch vụ, đổi đơn vị, lô/hạn dùng, bảo hành, trả góp.
5. **Data quality / ambiguity – điểm dễ sai?** Header nhiều dòng, tên viết tắt, trường lặp ở mỗi dòng, dữ liệu ghi chú tự do, ngày dạng text, thiếu ID.

## 2. Bảng phân loại 14 shop

| Shop | Mô hình bản ghi chính | Cách tổ chức | Họ cấu trúc đề xuất | Độ phức tạp Adapter |
|---|---|---|---|---|
| dev_001 | Dòng hàng hóa trong hóa đơn | Excel POS + danh mục hàng | A1 – POS line-item cơ bản | Trung bình |
| dev_002 | Dòng sản phẩm trong đơn | 17 file Excel theo tháng + bảng quy đổi | A2 – Monthly line-item, nối theo tên | Cao |
| dev_003 | Dòng hàng POS + sổ tay + báo cáo ca | Nhiều nguồn Excel/CSV | B1 – Hybrid multi-source | Rất cao |
| dev_004 | Dòng hàng trong sổ bán | Excel ghi tay, mỗi tháng một sheet, nhiều sổ phụ | B2 – Manual multi-ledger | Rất cao |
| dev_005 | Dòng sản phẩm trong đơn | 17 file Excel theo tháng + danh mục + lô | A3 – POS line-item có truy xuất lô | Rất cao |
| dev_006 | Bản ghi trong các bảng quan hệ | Một SQLite, 18 bảng | C1 – Relational POS database | Cao |
| dev_007 | Dòng hàng trong hóa đơn | 3 CSV: hóa đơn, danh mục, nhập hàng | A4 – Restaurant POS line-item | Cao |
| dev_008 | Dòng hàng trong hóa đơn | Nhiều Excel: hóa đơn, danh mục, nhập hàng | A4 – Restaurant POS line-item | Cao |
| dev_009 | Một hóa đơn | Một CSV, không có chi tiết hàng | D1 – Invoice summary | Trung bình |
| dev_010 | Đơn hàng, dòng hàng, lần thanh toán | 5 CSV quan hệ | C2 – Multi-CSV relational | Cao |
| dev_011 | Dòng hàng trong đơn | Excel ghi tay + bảng giải nghĩa viết tắt | B3 – Manual phone-sales ledger | Cao |
| dev_012 | Một lượt sửa xe / phiếu dịch vụ | Excel theo tháng + danh sách thợ | B4 – Service-ticket ledger | Rất cao |
| dev_013 | Dòng hàng và dòng điều chỉnh hóa đơn | Excel theo tháng + workbook quản lý | A5 – Mixed invoice rows | Rất cao |
| dev_014 | Dòng hàng + sự kiện nợ/góp/bảo hành/thu máy cũ | Nhiều sổ Excel liên kết | B5 – Manual phone ledger + subledgers | Rất cao |

Chi tiết từng shop và các quy tắc/rủi ro nằm trong `shop_classification.csv`.

## 3. Các họ cấu trúc có thể dùng để thiết kế Adapter

### A. POS line-item exports

**Thành viên:** dev_001, dev_002, dev_005, dev_007, dev_008, dev_013.

Đặc trưng chung:
- Dữ liệu bán hàng có thể biểu diễn thành nhiều dòng hàng cho một hóa đơn.
- Một số trường cấp hóa đơn được lặp lại trên từng dòng hàng.
- Thường có danh mục sản phẩm và/hoặc bảng quy đổi đơn vị ở nguồn phụ.

Nhưng không được coi cả nhóm là giống hệt nhau:
- dev_001 có mã hàng và cấu trúc tương đối gọn.
- dev_002 nối theo tên sản phẩm, dữ liệu chia thành 17 file tháng; topping có thể nằm chung trong tên món.
- dev_005 có lô/hạn sử dụng và phân bổ dòng bán theo lô.
- dev_007/dev_008 có ngữ nghĩa nhà hàng: bàn, khu vực, phí phục vụ, phí giao và các trường cấp đơn lặp lại.
- dev_013 có header 2 dòng và các dòng Voucher/Dùng điểm/Phí ship không phải dòng hàng.

**Hàm ý:** Có thể dùng chung một adapter nền cho line-item, nhưng phải có cấu hình/nhánh mở rộng cho batch, restaurant charges và invoice adjustments.

### B. Sổ Excel ghi tay / nhiều sổ nghiệp vụ

**Thành viên:** dev_003, dev_004, dev_011, dev_012, dev_014.

Đặc trưng:
- Header, cách ghi tên và quy tắc ghi chép phụ thuộc từng cửa hàng.
- Khóa liên kết có thể là số thứ tự sổ, IMEI, tên khách, tên hàng hoặc ghi chú.
- Dữ liệu phụ thường được lưu trong sổ riêng, không phải bảng quan hệ có schema rõ ràng.

Các khác biệt quan trọng:
- dev_003 là dữ liệu lai: có POS export nhưng ghép với sổ nhập hàng, chi phí, tồn kho và báo cáo tiền theo ca.
- dev_004 có giao hàng nhiều đợt, hạn nợ, lịch sử giá và hàng trả số lượng âm.
- dev_011/dev_014 là cửa hàng điện thoại, có IMEI, máy cũ/thu máy cũ và cách ghi tắt.
- dev_012 là dịch vụ sửa xe: một dòng = một lượt sửa, không có mã phiếu/khách, nhiều công việc trong một ô và chỉ có tổng tiền phiếu.

**Hàm ý:** Không thể ép toàn bộ nhóm này vào adapter bán lẻ line-item. Cần adapter theo loại sổ và khả năng liên kết; dev_012 cần một canonical model riêng cho service ticket.

### C. Dữ liệu quan hệ

**Thành viên:** dev_006, dev_010.

Đặc trưng:
- Nhiều bảng mô tả các thực thể/sự kiện khác nhau.
- Có khóa nối theo mã đơn, mã hàng, mã khách hoặc mã chứng từ.
- Các bảng thanh toán, trả hàng, tồn kho và lô hàng có grain riêng.

Khác biệt:
- dev_006 là SQLite POS với 18 bảng.
- dev_010 là 5 CSV rời: đơn hàng, chi tiết đơn, sản phẩm, khách hàng, thanh toán.

**Hàm ý:** Adapter phải đọc schema và ánh xạ quan hệ, không chỉ đọc từng file rồi nối tùy tiện. Đặc biệt, không join trực tiếp bảng payment nhiều dòng với order detail nhiều dòng rồi sum, vì có thể nhân bản số tiền.

### D. Hóa đơn chỉ có tổng hợp

**Thành viên:** dev_009.

Đặc trưng:
- Mỗi dòng là một hóa đơn.
- Không có chi tiết sản phẩm trong hóa đơn.
- Có tổng giá trị hàng, tổng khách phải trả, đã thu và nợ.

**Hàm ý:** Canonical model phải cho phép `invoice` tồn tại mà không có `invoice_items`. Không được tự suy diễn sản phẩm hoặc doanh thu theo mặt hàng từ dữ liệu tổng hợp.

## 4. Các đặc điểm chung thực sự có thể chuẩn hóa

| Khái niệm chuẩn hóa | Bằng chứng xuất hiện | Điều kiện / giới hạn |
|---|---|---|
| Ngày giao dịch | Phần lớn shop | Một số dòng điều chỉnh không có ngày riêng; có thể cần kế thừa ngày từ hóa đơn |
| Hóa đơn/đơn bán | Hầu hết shop bán lẻ | dev_012 là phiếu sửa dịch vụ; dev_009 chỉ có cấp hóa đơn |
| Dòng hàng | Nhiều shop bán lẻ | Không tồn tại ở dev_009; dev_013 có dòng điều chỉnh không phải hàng |
| Sản phẩm/dịch vụ | Có ở hầu hết mô hình | dev_012 ghi công việc tự do; một số shop nối theo tên thay vì ID |
| Số lượng và đơn vị | Nhiều shop bán hàng | Không phải lúc nào cũng có; quy đổi có thể ở file/sheet riêng hoặc ghi chú |
| Tổng tiền / thành tiền | Phổ biến | Có thể là tiền dòng, tiền đơn, tiền phiếu hoặc tiền lần thanh toán; phải phân biệt grain |
| Khách hàng | Phổ biến nhưng không bắt buộc | Có khách lẻ, thiếu mã khách, hoặc hoàn toàn không ghi khách như dev_012 |
| Trạng thái / ghi chú | Phổ biến | Có nơi có cột trạng thái; nơi khác mã hóa trong ghi chú hoặc số lượng âm |
| Thanh toán / công nợ | Nhiều shop | Có thể là số dư hiện tại, các lần thu tiền, hoặc khoản trả góp; không thể đồng nhất một cột |
| Danh mục sản phẩm | Nhiều shop | Có thể thiếu, nối bằng tên, hoặc nằm trong bảng quan hệ |

**Kết luận:** Nên chuẩn hóa khái niệm nghiệp vụ ở mức lõi, nhưng cho phép trường tùy chọn và quan hệ một-nhiều. Không nên đặt giả định mọi shop đều có đủ `customer_id`, `product_id`, `invoice_items`, `payment_transactions`, `stock` hay `purchase_orders`.

## 5. Những rủi ro xuyên suốt cần Generic Profiler phát hiện

1. **Grain mismatch:** cùng một file có trường cấp dòng và cấp hóa đơn lặp lại ở nhiều dòng.
2. **Join multiplication:** một đơn có nhiều dòng hàng và nhiều lần thanh toán; join hai bảng này trước khi aggregate sẽ làm phình số tiền.
3. **Missing identifiers:** nối bằng tên hàng/tên khách hoặc không có mã phiếu.
4. **Mixed row types:** dòng hàng và dòng voucher/điểm/ship nằm chung một bảng.
5. **Multi-file partition:** dữ liệu chia theo tháng/năm; cần kiểm tra thiếu tháng, trùng file và schema drift.
6. **Header irregularity:** header nhiều dòng, tên cột khác nhau, sheet phụ giải nghĩa viết tắt.
7. **Free-text semantics:** công việc sửa chữa, ghi chú trả hàng, bảo hành, nợ và tên viết tắt.
8. **Unit conversion:** số lượng nhập/bán có thể theo đơn vị lớn; hệ số quy đổi có thể theo nhiều tầng.
9. **Event-vs-snapshot confusion:** số dư nợ/tồn cuối khác với lịch sử từng lần thanh toán/biến động kho.
10. **Special business events:** trả hàng, đổi máy cũ, trả góp, bảo hành, phí phục vụ, phí giao và điều chỉnh hóa đơn.

## 6. Đề xuất hướng thiết kế tiếp theo

Không xây 14 adapter độc lập ngay từ đầu. Nên tách thành ba lớp:

```text
Raw source files
      |
      v
Source discovery
(format, sheets, tables, headers, candidate keys)
      |
      v
Adapter family
(POS line-item / manual ledger / relational / invoice summary / service ticket)
      |
      v
Shop-specific mapping & business rules
      |
      v
Canonical intermediate representation
      |
      v
Validation + profiling + query layer
```

- **Generic Profiler:** phát hiện cấu trúc vật lý, kiểu dữ liệu, null, unique, candidate keys, lặp theo nhóm, dấu hiệu grain và schema drift.
- **Family Adapter:** xử lý cách đọc phổ biến của từng họ.
- **Shop Configuration:** khai báo mapping cột, sheet, khóa nối và quy tắc đặc thù.
- **Validation:** kiểm tra tổng tiền, số lượng, khóa nối, bản ghi mồ côi và các quy tắc nghiệp vụ.

## 7. Những việc chưa được kết luận ở D2

- Chưa xác nhận toàn bộ khóa chính/khóa ngoại thực tế; README mô tả khóa nghiệp vụ nhưng cần kiểm tra dữ liệu.
- Chưa đo tỷ lệ null, duplicate, schema drift giữa các tháng và mức độ nhất quán tên hàng.
- Chưa xác nhận tất cả các sheet có header giống nhau.
- Chưa kết luận các trường tiền có thể cộng trực tiếp với nhau.
- Chưa chọn canonical schema cuối cùng.

Các mục này cần được kiểm chứng ở D3/D4 bằng profiling và đối soát trên dữ liệu thực tế, không chỉ dựa vào mô tả.

## 8. Nguồn khảo sát

- `public_test/data/dev_001/README.md` đến `dev_014/README.md`
- D1 inventory: `docs/data_discovery/D1_data_inventory/README.md`
- D1 inventory object-level: `docs/data_discovery/D1_data_inventory/data_inventory.csv`
