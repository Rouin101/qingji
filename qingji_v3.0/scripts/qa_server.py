"""Isolated local QA server with a provider rejection stub and outgoing HTTP audit."""
import argparse, json, os, sys, threading, urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from scripts.qa_support import qa_database

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir',required=True)
    parser.add_argument('--audit-file',required=True)
    parser.add_argument('--port',required=True,type=int)
    args=parser.parse_args()
    database=qa_database(Path(args.data_dir)/'projects.sqlite3',existing=True)
    audit=Path(args.audit_file).resolve()
    audit.relative_to((ROOT/'design/iterations').resolve())
    if audit.exists(): raise ValueError('Refuse to overwrite an existing server audit')
    audit.parent.mkdir(parents=True,exist_ok=True)
    events=[]; lock=threading.Lock()
    def record(kind):
        with lock:
            events.append({'kind':kind})
            audit.write_text(json.dumps({'model_attempts':sum(e['kind']=='completion' for e in events),'outgoing_http_attempts':sum(e['kind']=='outgoing_http' for e in events),'events':events},indent=2),encoding='utf-8')
    audit.write_text(json.dumps({'model_attempts':0,'outgoing_http_attempts':0,'events':[]}),encoding='utf-8')
    os.environ['QINGJI_V3_DATA_DIR']=str(database.parent)
    for key,value in [('QINGJI_V3_API_KEY','qa-denied'),('QINGJI_V3_API_BASE','http://127.0.0.1:9'),('QINGJI_V3_MODEL','qa-controlled')]:os.environ[key]=value
    import core.review as review
    review.load_ai_config=lambda:None
    def deny_completion(*args,**kwargs):
        record('completion')
        raise review.ReviewError('QA refuses real model calls')
    def deny_http(*args,**kwargs):
        record('outgoing_http')
        raise OSError('QA refuses outgoing HTTP')
    review.configured_completion=deny_completion
    urllib.request.OpenerDirector.open=deny_http
    import server
    server.configured_completion=deny_completion
    sys.argv=['qa_server','--port',str(args.port)]
    server.main()

if __name__=='__main__':main()
