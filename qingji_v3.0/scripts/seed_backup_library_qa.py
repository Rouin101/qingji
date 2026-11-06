"""Seed a synthetic orphan backup and an unrelated surviving project; never touch real data."""
import json
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from core.projects import ProjectStore
from core.project_backups import create_backup,connect
from scripts.qa_support import qa_database


def main():
    path=qa_database(ROOT/'.browser-test-output/backup-library-20261106/projects.sqlite3')
    store=ProjectStore(path)
    name='虚构遗失项目-'+str(time.time_ns())
    p=store.create(name,{'text':'备份中的原报告'})
    backup=create_backup(store,p['id'],p['version'])[0]
    # Only this fixture's project is removed, not any existing QA or user database.
    db=store.connect()
    with db:db.execute('DELETE FROM projects WHERE id=?',(p['id'],))
    db.close()
    kept=store.create('虚构保留项目-'+str(time.time_ns()),{'text':'保持原样'})
    other=create_backup(store,kept['id'],kept['version'])[0]
    # Separate malformed fixture demonstrates preview refusal without touching a valid backup.
    broken='broken'+str(time.time_ns());db=connect(store)
    with db:db.execute('INSERT INTO backups VALUES (?,?,?,?,?,?,?)',(broken,'orphan-corrupt',1,'2026-11-06T00:00:00+00:00','虚构损坏备份',2,'{}'))
    db.close()
    out=ROOT/'design/iterations/2026-11-06/backup-library';out.mkdir(parents=True,exist_ok=True)
    (out/'seed.json').write_text(json.dumps({'name':name,'source_id':p['id'],'backup_id':backup['id'],'kept':kept,'other':other,'broken':broken}),encoding='utf-8')
    print('Seeded synthetic orphan backups. Start qa_server on port 8786.')


if __name__=='__main__':main()
