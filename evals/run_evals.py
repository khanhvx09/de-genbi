"""
Chạy golden set qua agent (gọi trực tiếp, không cần server) và chấm điểm theo các member Cube mà agent đã dùng.
  python evals/run_evals.py
Đây là "query-shape accuracy". Bước sau: so kết quả số với query chuẩn (execution accuracy).
"""
import argparse
import pathlib
import sys
import uuid

import yaml
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(pathlib.Path(__file__).parents[1] / "app"))
from agent import ask, build_agent  # noqa: E402


def members_of(q: dict) -> set[str]:
    s = set(q.get("measures", [])) | set(q.get("dimensions", []))
    s |= {t["dimension"] for t in q.get("timeDimensions", [])}
    s |= {f["member"] for f in q.get("filters", []) if "member" in f}
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(pathlib.Path(__file__).with_name("golden_questions.yaml")))
    a = ap.parse_args()
    cases = yaml.safe_load(open(a.file))
    agent = build_agent()
    passed = 0
    for c in cases:
        r = ask(agent, c["question"], f"eval-{uuid.uuid4()}", "eval")
        queries = [x["query"] for x in r.get("results", [])]
        used = set().union(*(members_of(q) for q in queries)) if queries else set()
        if c.get("expect_no_query"):
            ok = not queries
        else:
            ok = bool(queries) and set(c["must_include"]) <= used
            if ok and c.get("granularity"):
                ok = any(t.get("granularity") == c["granularity"]
                         for q in queries for t in q.get("timeDimensions", []))
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  {c['id']}  {c['question']}")
        if not ok:
            print(f"      used={sorted(used)}")
    print(f"\n{passed}/{len(cases)} passed ({passed / len(cases):.0%})")


if __name__ == "__main__":
    main()
