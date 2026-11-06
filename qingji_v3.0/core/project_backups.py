"""Explicit local snapshots, stored separately from the working project database."""
import json
import sqlite3
import uuid
from contextlib import closing
from core.projects import ProjectConflict
from core.project_packages import export_package, import_package, validate_package, _json_bytes
from core.review import ReviewError

MAX_BACKUPS = 20


def connect(store):
    store.path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(store.path.with_name(store.path.stem + '-backups.sqlite3'), timeout=20)
    db.execute('CREATE TABLE IF NOT EXISTS backups (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, version INTEGER NOT NULL, created_at TEXT NOT NULL, name TEXT NOT NULL, size INTEGER NOT NULL, data TEXT NOT NULL)')
    db.commit()
    return db


def list_backups(store, project_id):
    with closing(connect(store)) as db:
        rows = db.execute('SELECT id,version,created_at,name,size FROM backups WHERE project_id=? ORDER BY rowid DESC', (project_id,)).fetchall()
    return [dict(zip(('id','version','created_at','name','size'), row)) for row in rows]


def create_backup(store, project_id, version):
    package = export_package(store, project_id)
    project = package['payload']['project']
    if type(version) is not int or version != project['version']:
        raise ProjectConflict('项目已更新，请重新打开后保存备份。')
    content = _json_bytes(package).decode('utf-8')
    with closing(connect(store)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        # Repeated clicks cannot consume slots for the same project version.
        existing = any(json.loads(row[0]).get('sha256')==package['sha256'] for row in db.execute('SELECT data FROM backups WHERE project_id=? AND version=?', (project_id,version)))
        if not existing:
            if db.execute('SELECT COUNT(*) FROM backups WHERE project_id=?', (project_id,)).fetchone()[0] >= MAX_BACKUPS:
                raise ReviewError('每个项目最多保留 20 份本机备份；请先下载并删除不再需要的备份。')
            db.execute('INSERT INTO backups VALUES (?,?,?,?,?,?,?)', (uuid.uuid4().hex,project_id,version,package['exported_at'],project['name'],len(content.encode('utf-8')),content))
    return list_backups(store, project_id)


def read_backup(store, project_id, backup_id):
    with closing(connect(store)) as db:
        row = db.execute('SELECT data FROM backups WHERE project_id=? AND id=?', (project_id,backup_id)).fetchone()
    if not row:
        raise ReviewError('找不到这份项目备份，请刷新列表。')
    try:
        return json.loads(row[0])
    except (ValueError, TypeError) as exc:
        raise ReviewError('备份内容无法读取，原项目未被更改。') from exc


def restore_backup(store, project_id, backup_id, actor=''):
    # Shared package validation checks all relations and digest before any write.
    return import_package(store, read_backup(store, project_id, backup_id), actor)


def delete_backup(store, project_id, backup_id):
    with closing(connect(store)) as db, db:
        cursor = db.execute('DELETE FROM backups WHERE project_id=? AND id=?', (project_id,backup_id))
        if not cursor.rowcount:
            raise ReviewError('找不到这份项目备份，请刷新列表。')
    return list_backups(store, project_id)


def backup_library(store, query='', page=0):
    if not isinstance(query,str) or len(query)>200 or type(page) is not int or not 0<=page<=10000:
        raise ReviewError('备份搜索条件无效。')
    # Literal substring search: SQL wildcard characters in names have no special meaning.
    with closing(connect(store)) as db:
        db.execute('BEGIN')
        params=(query.strip(),)
        where='WHERE instr(lower(name),lower(?))>0'
        total=db.execute('SELECT COUNT(*) FROM backups '+where,params).fetchone()[0]
        rows=db.execute('SELECT id,project_id,version,created_at,name,size FROM backups '+where+' ORDER BY rowid DESC LIMIT 20 OFFSET ?',params+(page*20,)).fetchall()
    return {'backups':[dict(zip(('id','project_id','version','created_at','name','size'),row)) for row in rows],
            'total':total,'page':page,'page_size':20}


def preview_backup(store, project_id, backup_id):
    package=read_backup(store,project_id,backup_id)
    payload=validate_package(package)
    p=payload['project']
    if p['id']!=project_id:raise ReviewError('备份来源标识不匹配，请使用完整原文件。')
    state=p.get('lifecycle') or {}
    saved={'name':p['name'],'version':p['version'],'updated_at':p['updated_at'],
           'materials':len(p['materials']),'tasks':len(p['tasks']),
           'observations':len(state.get('observations',[])),'questions':[q['text'] for q in state.get('questions',[])],
           'reviews':len(payload['revisions']),'analyses':len(payload.get('analyses',[])),
           'report_chars':len(p['report']['text']),'report_name':p['report']['name']}
    current=None;availability='missing'
    try:
        if not store.path.exists():raise ReviewError("找不到原项目库。")
        value=store.get(project_id)
        current={'name':value['name'],'version':value['version'],'updated_at':value['updated_at'],
                 'materials':len(value['materials']),'tasks':len(value['tasks'])}
        availability='available'
    except ReviewError:
        pass
    except sqlite3.DatabaseError:
        availability='unreadable'
    return {'saved':saved,'current':current,'availability':availability,'package_version':package['schema_version'],
            'exported_at':package['exported_at']}
