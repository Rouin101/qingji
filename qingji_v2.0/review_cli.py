"""独立审核核心的临时入口；界面选定后由网页调用相同核心。"""

import argparse
import json
import pathlib
import sys

from core.review import (ReviewError, configured_completion, preliminary_review,
                         read_document, review_with_model)


def main() -> int:
    parser = argparse.ArgumentParser(description="青迹 2.0：社会实践报告检查")
    parser.add_argument("report", type=pathlib.Path, help="DOCX、TXT 或 Markdown 报告")
    parser.add_argument("--material", type=pathlib.Path, action="append", default=[], help="可多次指定补充材料")
    parser.add_argument("--ai", action="store_true", help="将本次报告与材料发送至独立配置的 AI 服务进行审核")
    parser.add_argument("--output", type=pathlib.Path, help="保存 JSON，输出位置必须在 qingji_v2.0 内")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    try:
        output = None
        if args.output:
            output = args.output.resolve()
            if not output.is_relative_to(pathlib.Path(__file__).resolve().parent):
                raise ReviewError("输出请保存到 qingji_v2.0 内，避免写入保留的旧版本。")
        report = read_document(args.report.name, args.report.read_bytes())
        materials = [read_document(p.name, p.read_bytes(), f"m{i + 1}") for i, p in enumerate(args.material)]
        result = (review_with_model(report, materials, configured_completion) if args.ai
                  else preliminary_review(report, materials))
        serialized = json.dumps(result.to_dict(), ensure_ascii=False, indent=2)
        if output:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(serialized + "\n", encoding="utf-8")
            print(f"检查记录已保存：{output}")
        else:
            print(serialized)
        return 0
    except (ReviewError, OSError) as exc:
        print(f"未完成检查：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
