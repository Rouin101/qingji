import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import server
from core.projects import ProjectStore, ProjectConflict
from core.review import ReviewError
from core.lifecycle import save_brief, add_observation
from core import project_backups as backups


class BackupTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.store=ProjectStore(Path(temp.name)/'projects.sqlite3')
        self.p=self.store.create('虚构备份项目', {'text':'保存前的正文'})

    def create(self,p=None):
        p=p or self.p
        return backups.create_backup(self.store,p['id'],p['version'])[0]

    def test_restore_keeps_relations_and_original(self):
        p=save_brief(self.store,self.p['id'],self.p['version'],{'topic':'访谈','goal':'了解情况'},[{'id':'q1','text':'有何困难？'}],'field')
        p=add_observation(self.store,p['id'],p['version'],{'question_id':'q1','text':'虚构记录','finding':'某次遇到困难','consent_status':'confirmed'})
        b=self.create(p)
        latest=self.store.save(p['id'],p['version'],{'report':{'text':'之后修改正文'}})
        restored=backups.restore_backup(self.store,p['id'],b['id'])
        self.assertNotEqual(restored['id'],p['id'])
        self.assertEqual(restored['report']['text'],'保存前的正文')
        self.assertEqual(restored['lifecycle']['observations'],p['lifecycle']['observations'])
        self.assertEqual(self.store.get(p['id']),latest)
        self.assertTrue(restored['needs_review'])
        self.assertEqual(len(backups.list_backups(self.store,p['id'])),1)

    def test_history_preserved_without_model_call(self):
        with patch.object(server,'STORE',self.store),patch.object(server,'configured_completion',side_effect=AssertionError('no AI')):
            p=server.project_action({'action':'example'})
            b=self.create(p)
            restored=server.project_action({'action':'backup_restore','id':p['id'],'backup_id':b['id']})
        self.assertEqual(len(restored['history']),len(p['history']))
        self.assertTrue(all(h['imported_unverified'] for h in restored['history']))

    def test_stale_version_and_duplicate(self):
        self.create();self.create()
        self.assertEqual(len(backups.list_backups(self.store,self.p['id'])),1)
        with self.assertRaises(ProjectConflict):backups.create_backup(self.store,self.p['id'],0)
        self.assertEqual(self.store.get(self.p['id'])['version'],1)

    def test_scope_and_exact_delete(self):
        b=self.create();other=self.store.create('另一项目')
        for fn in (backups.read_backup,backups.delete_backup,backups.restore_backup):
            with self.assertRaises(ReviewError):fn(self.store,other['id'],b['id'])
        self.assertEqual(backups.delete_backup(self.store,self.p['id'],b['id']),[])
        self.assertEqual(self.store.get(self.p['id'])['report']['text'],'保存前的正文')

    def test_corruption_fails_without_partial_import(self):
        b=self.create()
        db=backups.connect(self.store)
        data=backups.read_backup(self.store,self.p['id'],b['id'])
        data['payload']['project']['name']='篡改'
        with db:db.execute('UPDATE backups SET data=? WHERE id=?',(json.dumps(data),b['id']))
        db.close()
        with self.assertRaises(ReviewError):backups.restore_backup(self.store,self.p['id'],b['id'])
        self.assertEqual(len(self.store.list()),1)

    def test_limit_does_not_evict_and_separate_database(self):
        self.create()
        p=self.store.save(self.p['id'],1,{'name':'新版本'})
        with patch.object(backups,'MAX_BACKUPS',1):
            with self.assertRaises(ReviewError):self.create(p)
        self.assertEqual(len(backups.list_backups(self.store,p['id'])),1)
        # Loss of the working database does not remove the separate snapshot.
        self.store.path.unlink()
        b=backups.list_backups(self.store,p['id'])[0]
        restored=backups.restore_backup(self.store,p['id'],b['id'])
        self.assertEqual(restored['name'],'虚构备份项目（交接副本）')
