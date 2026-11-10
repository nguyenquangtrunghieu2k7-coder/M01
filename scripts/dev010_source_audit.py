#!/usr/bin/env python3
"""Read-only dev_010 source audit. Does not modify CSV or approved shops."""
import argparse, csv, hashlib, json, collections, pathlib, re
FILES={"orders":"don_hang.csv","lines":"chi_tiet_don.csv","payments":"thanh_toan.csv","customers":"khach_hang.csv","products":"san_pham.csv"}
KEYS={"orders":"Số CT","lines":"Mã bill","payments":"Mã TT","customers":"Mã khách","products":"Mã vạch"}
ORDER=re.compile(r"^ORD[0-9]{6}$")
PAY=re.compile(r"^PAY[0-9]{6}$")
def load(p):
    with p.open("r",encoding="utf-8-sig",newline="") as f:
        reader=csv.DictReader(f)
        return reader.fieldnames,list(reader)
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--source",default=str(pathlib.Path.home()/"Downloads/public_test/data/dev_010"))
    p.add_argument("--output",default="outputs/dev010_source_audit.json")
    args=p.parse_args()
    src=pathlib.Path(args.source)
    result={"shop":"dev_010","status":"SOURCE_AUDIT_ONLY","files":{},"joins":{},"warnings":[]}
    data={}
    for kind,name in FILES.items():
        path=src/name
        if not path.is_file(): raise SystemExit(f"Missing source: {path}")
        fields,rows=load(path)
        if KEYS[kind] not in fields: raise SystemExit(f"Missing key {KEYS[kind]} in {name}")
        data[kind]=rows
        ids=[str(r.get(KEYS[kind]) or "").strip() for r in rows]
        repeated=sum(x==KEYS[kind] for x in ids)
        result["files"][name]={"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"rows":len(rows),"columns":fields,"repeated_headers":repeated,"empty_keys":sum(not x for x in ids),"duplicate_key_rows":sum(n-1 for n in collections.Counter(ids).values() if n>1)}
    orders=data["orders"];lines=data["lines"];payments=data["payments"]
    order_ids=[str(r.get("Số CT") or "").strip() for r in orders if ORDER.fullmatch(str(r.get("Số CT") or "").strip())]
    line_ids=[str(r.get("Mã bill") or "").strip() for r in lines if ORDER.fullmatch(str(r.get("Mã bill") or "").strip())]
    payment_ids=[str(r.get("Mã đơn") or "").strip() for r in payments if PAY.fullmatch(str(r.get("Mã TT") or "").strip())]
    os=set(order_ids);ls=set(line_ids);ps=set(payment_ids)
    result["joins"]={"transaction_order_rows":len(order_ids),"distinct_orders":len(os),"duplicate_order_ids":sum(n-1 for n in collections.Counter(order_ids).values() if n>1),"transaction_line_rows":len(line_ids),"orphan_line_rows":sum(x not in os for x in line_ids),"orders_without_lines":len(os-ls),"payment_rows_with_valid_payment_id":len(payment_ids),"orphan_payment_rows":sum(x not in os for x in payment_ids),"orders_without_payments":len(os-ps),"nontransaction_order_rows":len(orders)-len(order_ids),"nontransaction_line_rows":len(lines)-len(line_ids)}
    for kind,columns in {"orders":["Thành tiền","Tiền giảm","Phí vận chuyển","Khách trả","Con no"],"lines":["Cộng","CK","Đơn giá (đ)"],"payments":["So tien"]}.items():
        for col in columns:
            if col not in result["files"][FILES[kind]]["columns"]:raise SystemExit(f"Missing money column: {kind}.{col}")
            values=[str(r.get(col) or "").strip() for r in data[kind]]
            unusual=collections.Counter(v for v in values if v and not re.fullmatch(r"-?[0-9][0-9,. ]*",v))
            result["files"][FILES[kind]].setdefault("unusual_money",{})[col]={"count":sum(unusual.values()),"examples":unusual.most_common(12)}
    result["warnings"].append("No revenue KPI is approved by this source-only audit.")
    output=pathlib.Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"report":str(output),"joins":result["joins"],"unusual_money":{k:{c:v["count"] for c,v in x.get("unusual_money",{}).items()} for k,x in result["files"].items()}},ensure_ascii=False,indent=2))
if __name__=="__main__":main()
