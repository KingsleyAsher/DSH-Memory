import json
import tempfile
import unittest
from memory_core.plugin_bridge import PluginBridge


class WriteReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.b=PluginBridge(self.tmp.name)
    def tearDown(self):self.b.close();self.tmp.cleanup()
    def prepare(self,text):
        self.b.ingest('s','D:/p',[dict(id='m',role='user',text=text)])
        return self.b.prepare_active('s','D:/p',['m'])['batches'][0]
    def body(self,value):
        return dict(items=[dict(id='S1',f=[dict(v=value,e=[1],a='规则',t='',l='global')],o=[dict(op='assert')])],skips=[])
    def test_original_failure_restores_literal_and_binds_record_without_mutating_response(self):
        # Synthetic three-segment rule with punctuation-only transport differences.
        self.b.flow.ingest(dict(id='raw',session_id='s',project='p',entity='workspace',role='user',text='以后所有的实验记录。 解析完都要做成。 PDF的实验报告。'))
        p=self.b.flow.prepare('active','s')
        value=self.body('以后所有的实验记录，解析完都要做成 PDF 的实验报告。')
        value['items'][0]['f'][0]['e']=[1,2,3]
        out=self.b.submit('s',p['batch_id'],value)
        self.assertEqual(out['state'],'saved');self.assertTrue(out['can_confirm_saved'])
        self.assertEqual(len(out['results'][0]['transport_repairs']),2)
        row=self.b.db.execute('SELECT response FROM memory_flow_batches WHERE id=?',(p['batch_id'],)).fetchone()
        self.assertEqual(json.loads(row[0]),value)
        self.assertEqual(self.b.submit('s',p['batch_id'],value),out)
    def test_changed_words_rejected_then_fresh_batch_retry_succeeds(self):
        p=self.prepare('不要自动上传文件。')
        bad=self.b.submit('s',p['batch_id'],self.body('允许自动上传文件。'))
        self.assertEqual(bad['state'],'not_saved');self.assertFalse(bad['can_confirm_saved'])
        self.assertFalse(self.b.scopes.list('w')['entries'])
        fresh=self.b.prepare_active('s','D:/p',['m'])['batches'][0]
        good=self.b.submit('s',fresh['batch_id'],self.body('不要自动上传文件。'))
        self.assertTrue(good['can_confirm_saved'])
    def test_empty_tool_call_is_not_save_success(self):
        p=self.prepare('不要自动上传文件。')
        out=self.b.submit('s',p['batch_id'],dict(items=[],skips=[]))
        self.assertEqual(out['state'],'not_saved');self.assertFalse(out['can_confirm_saved'])
    def test_numeric_punctuation_never_repaired(self):
        p=self.prepare('负数是-1。')
        out=self.b.submit('s',p['batch_id'],self.body('负数是1。'))
        self.assertFalse(out['can_confirm_saved'])
    def test_explicit_rule_is_global_durable_and_bound_to_original_source(self):
        text='以后所有的实验记录。 解析完都要做成。 PDF的实验报告。'
        self.b.ingest('s','D:/p',[dict(id='m',role='user',text=text)])
        entries=self.b.scopes.list('w')['entries']
        self.assertEqual(len(entries),1);self.assertEqual(entries[0]['scope'],'global')
        self.assertEqual(entries[0]['text'],text)
        self.assertFalse(self.b.db.execute("SELECT 1 FROM inbox WHERE id LIKE 'manual-%'").fetchone())
    def test_same_project_agents_share_scope_and_switch_preserves_memory(self):
        b=self.b
        b.scopes.activate('wa','D:/a','agent-1')
        b.scopes.add('wa','project','项目A专用。','项目要求',request_id='p')
        b.scopes.add('wa','global','全局使用中文。','语言',request_id='g')
        b.scopes.activate('wb','D:/a','agent-2')
        self.assertEqual(len(b.scopes.list('wb')['entries']),2)
        b.scopes.activate('wa','D:/b','agent-3')
        self.assertEqual(len(b.scopes.list('wa')['entries']),1)
        b.scopes.activate('wa',None)
        self.assertEqual([e['scope'] for e in b.scopes.list('wa')['entries']],['global'])
        b.scopes.activate('wa','D:/a','agent-4')
        self.assertEqual(len(b.scopes.list('wa')['entries']),2)
        recalled=b.dispatch(dict(op='query',args=dict(session='agent-3',project='D:/b',question='项目要求？')))
        self.assertFalse(any('项目A' in e['value'] for e in recalled['evidence']))

    def test_old_per_window_keys_share_only_the_same_project(self):
        b=self.b
        b.scopes.activate('old','D:/a','old-agent')
        b.scopes.add('old','project','A项目只用蓝色。','颜色',request_id='old')
        # Simulate another window key created by the previous plugin version.
        with b.db:
            b.db.execute('INSERT INTO plugin_context_labels VALUES(?,?)',('legacy-other-window','D:/a'))
            b.db.execute('INSERT INTO plugin_windows VALUES(?,?,?)',('new','D:/a','legacy-other-window'))
        self.assertEqual(len(b.scopes.list('new')['entries']),1)
        self.assertTrue(any('蓝色' in r['value'] for r in b.scopes.evidence('legacy-other-window','颜色')))
        self.assertFalse(b.scopes.evidence('D:/b','颜色'))


if __name__=='__main__':unittest.main()
