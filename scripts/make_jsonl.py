import json
import pathlib

text = pathlib.Path("examples/小米景明汽车谣言.md").read_text(encoding="utf-8").strip()

record = {
    "raw_text": text,
    "title": "小米注册景明子公司规避法律责任",
    "tags": ["小米汽车", "法律", "子公司", "消费者维权"],
    "is_published": True,
}

out = pathlib.Path("examples/小米景明汽车谣言.jsonl")
out.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
print("written:", out)
print("first 60 chars:", out.read_text(encoding="utf-8")[:60])
