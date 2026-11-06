"""Run from v3: python -B scripts/evaluate_synthesis.py [--live]."""
import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from evaluation.synthesis import run_suite, write_report, compare_runs


def main():
    parser = argparse.ArgumentParser(description='虚构阶段分析评估；默认回放不调用模型。')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--live',action='store_true',help='通过3.0配置调用真实模型，固定6例，每例至多一次，不重试')
    modes.add_argument('--compare',nargs=2,metavar=('BEFORE','AFTER'),help='比较两个原始 results.json，不调用模型')
    args = parser.parse_args()
    if args.compare:
        try:
            reports = [json.loads(Path(p).read_text('utf-8')) for p in args.compare]
            print(json.dumps(compare_runs(*reports),ensure_ascii=False,indent=2))
        except (OSError,ValueError,KeyError,TypeError):
            parser.error('无法比较：请使用完整、未修改且运行方式、案例集和输入一致的 results.json。')
        return 0
    complete = None
    if args.live:
        from core.review import configured_completion
        complete = configured_completion
    report = run_suite(complete)
    name = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]
    output = ROOT/'output/evaluations'/name
    write_report(report,output)
    passed = sum(row['structural_status']=='passed' for row in report['cases'])
    print(json.dumps({'mode':report['mode'],'structural_passed':passed,'total':len(report['cases']),
                      'model_calls':report['model_calls'],'semantic_review':'pending','report':str(output/'review.html')},ensure_ascii=False))
    return 0 if passed==len(report['cases']) else 1


if __name__=='__main__':
    sys.exit(main())
