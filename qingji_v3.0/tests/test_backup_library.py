import json
import tempfile
import unittest
from pathlib import Path
from core.projects import ProjectStore
from core.project_backups import create_backup,backup_library,preview_backup,restore_backup,connect
from core.review import ReviewError


class BackupLibraryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=ProjectStore(Path(temp.name)/'projects.sqlite3')
        self.p=self.store.create('虚构100%_项目',{'text':'备份中的报告'})
        self.backup=create_backup(self.store,self.p['id'],self.p['version'])[0]
    def test_preview_compares_without_mutating_current_project(self):
        p=self.store.save(self.p['id'],self.p['version'],{'report':{'text':'当前报告已修改'}})
        result=preview_backup(self.store,p['id'],self.backup['id'])
        self.assertEqual(result['saved']['version'],1);self.assertEqual(result['current']['version'],2)
        self.assertEqual(result['saved']['report_chars'],6)
        self.assertEqual(self.store.get(p['id']),p)
    def test_library_and_restore_after_working_database_loss(self):
        self.store.path.unlink()
        items=backup_library(self.store)['backups'];self.assertEqual(items[0]['project_id'],self.p['id'])
        result=preview_backup(self.store,self.p['id'],self.backup['id']);self.assertEqual(result['availability'],'missing')
        self.assertFalse(self.store.path.exists())
        restored=restore_backup(self.store,self.p['id'],self.backup['id'])
        self.assertEqual(restored['report']['text'],'备份中的报告');self.assertNotEqual(restored['id'],self.p['id'])
    def test_literal_search_and_pagination_never_expose_payload(self):
        db=connect(self.store)
        with db:
            db.executemany('INSERT INTO backups VALUES (?,?,?,?,?,?,?)',[(f'fake{i}','other',1,'2026-11-06T00:00:00+00:00','分组'+str(i),2,'{}') for i in range(25)])
        db.close()
        self.assertEqual(backup_library(self.store,'%')['total'],1)
        self.assertEqual(backup_library(self.store,"' OR 1=1 --")['total'],0)
        a=backup_library(self.store,'分组',0);b=backup_library(self.store,'分组',1)
        self.assertEqual(len(a['backups']),20);self.assertEqual(len(b['backups']),5)
        self.assertFalse({x['id'] for x in a['backups']} & {x['id'] for x in b['backups']})
        self.assertTrue(all('data' not in x for x in a['backups']))
        for page in (-1,True,10001):
            with self.assertRaises(ReviewError):backup_library(self.store,page=page)
    def test_corrupt_package_not_previewed_or_restored(self):
        db=connect(self.store)
        with db:
            data=json.loads(db.execute('SELECT data FROM backups WHERE id=?',(self.backup['id'],)).fetchone()[0]);data['payload']['project']['name']='篡改'
            db.execute('UPDATE backups SET data=? WHERE id=?',(json.dumps(data),self.backup['id']))
        db.close()
        for call in (preview_backup,restore_backup):
            with self.assertRaises(ReviewError):call(self.store,self.p['id'],self.backup['id'])
        self.assertEqual(self.store.get(self.p['id']),self.p)
    def test_unreadable_working_database_does_not_destroy_backup(self):
        self.store.path.write_bytes(b'not a database')
        result=preview_backup(self.store,self.p['id'],self.backup['id'])
        self.assertEqual(result['availability'],'unreadable')
        self.assertEqual(backup_library(self.store)['total'],1)
