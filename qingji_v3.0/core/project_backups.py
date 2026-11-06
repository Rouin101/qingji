"""Explicit local snapshots, stored separately from the working project database."""
import json
import sqlite3
import uuid
from contextlib import closing
from core.projects import ProjectConflict
from core.project_packages import export_package, import_package, _json_bytes
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
        existing = db.execute('SELECT id FROM backups WHERE project_id=? AND version=?', (project_id,version)).fetchone()
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
