"""Seed validated synthetic history for frontend/scripts/analysis-history-qa.mjs. No AI calls."""
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from core.projects import ProjectStore
from core.lifecycle import save_brief,add_observation
from core.question_synthesis import synthesize
from core.analysis_history import save_analysis
from scripts.qa_support import qa_database


def main():
    store=ProjectStore(qa_database(ROOT/'.browser-test-output/history-20261106/projects.sqlite3'))
    p=store.create('虚构分析历史浏览器-'+str(time.time_ns()))
    p=save_brief(store,p['id'],p['version'],{'topic':'虚构服务观察','goal':'了解情况'},[{'id':'q1','text':'遇到哪些困难？'}],'field')
    p=add_observation(store,p['id'],p['version'],{'question_id':'q1','text':'甲在最后一步需要帮助。','consent_status':'confirmed'})
    o=p['lifecycle']['observations'][0]
    for label in ['第一轮候选','第二轮候选']:
        data={'findings':[{'text':label,'citations':[{'observation_id':o['id'],'material_id':o['material_id'],'quote':'甲在最后一步需要帮助。'}]}],'differences':[],'questions':[],'limits':['仅一次记录']}
        save_analysis(store,p,synthesize(p,'q1',lambda _:json.dumps(data)))
    out=ROOT/'design/iterations/2026-11-06/history';out.mkdir(parents=True,exist_ok=True)
    (out/'seed.json').write_text(json.dumps({'id':p['id'],'name':p['name']}),'utf-8')
    print('Synthetic history seeded; start qa_server on port 8785 and run analysis-history-qa.mjs.')


if __name__=='__main__':main()
