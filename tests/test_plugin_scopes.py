import tempfile
import unittest
from memory_core.plugin_bridge import PluginBridge


class PluginScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.bridge=PluginBridge(self.temp.name)
        self.bridge.scopes.activate('window-a','D:/project-a','session-a')
    def tearDown(self):self.bridge.close();self.temp.cleanup()
    def test_manual_scopes_switch_clear_and_no_resurrection(self):
        b=self.bridge
        b.scopes.add('window-a','global','默认用中文答复。','语言',request_id='g1')
        b.scopes.add('window-a','project','装袋每份十八粒。','装袋',request_id='p1')
        self.assertEqual({r['scope'] for r in b.scopes.list('window-a')['entries']},{'global','project'})
        b.scopes.activate('window-b','D:/project-b','session-b')
        self.assertEqual(len(b.scopes.list('window-b')['entries']),1)
        b.scopes.add('window-b','project','只输出A4 PDF。','交付',request_id='p2')
        b.scopes.activate('window-a','D:/next-project','session-next',clear=True)
        self.assertEqual([r['text'] for r in b.scopes.list('window-a')['entries']],['默认用中文答复。'])
        self.assertEqual(len(b.scopes.list('window-b')['entries']),2)
        rows=b.db.execute("SELECT payload FROM inbox WHERE state!='deleted'").fetchall()
        self.assertFalse(any('十八粒' in r[0] for r in rows))
    def test_automatic_global_survives_and_project_sources_are_erased(self):
        b=self.bridge
        text='以后只发文字。不要只靠红绿区分。'
        b.ingest('session-a','D:/project-a',[dict(id='u1',role='user',text=text)])
        prepared=b.prepare_active('session-a','D:/project-a',['u1'])['batches'][0]
        handle=prepared['request']['payload']['write_sources'][0]
        result=b.submit('session-a',prepared['batch_id'],dict(items=[dict(id=handle,
            f=[dict(v='以后只发文字',e=[1],a='答复偏好',t='',f='pref',l='global'),dict(v='不要只靠红绿区分',e=[2],a='项目呈现',t='',f='rule',l='project')],
            o=[dict(op='assert',n='F0'),dict(op='assert',n='F1')])],skips=[]))
        self.assertEqual(result['results'][0]['state'],'saved')
        self.assertEqual({r['scope'] for r in b.scopes.list('window-a')['entries']},{'global','project'})
        b.scopes.activate('window-a','D:/next-project','session-next',clear=True)
        rows=b.scopes.list('window-a')['entries']
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['scope'],'global')
        recalled=b.dispatch(dict(op='query',args=dict(session='session-next',project='D:/next-project',question='答复习惯是什么？')))
        self.assertTrue(any('只发文字' in r['value'] for r in recalled['evidence']))
        self.assertFalse(any('红绿' in r['value'] for r in recalled['evidence']))
        self.assertEqual(b.ingest('session-a','D:/project-a',[dict(id='u1',role='user',text=text)])['state'],'retired_project')
        self.assertFalse(b.core.store.facts())
    def test_same_project_clear_does_not_reimport_old_history(self):
        b=self.bridge
        b.ingest('session-a','D:/project-a',[dict(id='u1',role='user',text='以后只发文字。')])
        b.scopes.activate('window-a','D:/project-a','session-a',clear=True)
        self.assertFalse(b.ingest('session-a','D:/project-a',[dict(id='u1',role='user',text='以后只发文字。')])['saved'])
        self.assertTrue(b.ingest('session-a','D:/project-a',[dict(id='u2',role='user',text='新的要求。')])['saved'])
    def test_idempotent_manual_add_delete_and_no_active_project(self):
        b=self.bridge
        first=b.scopes.add('window-a','global','以后只发文字。','答复',request_id='same')
        second=b.scopes.add('window-a','global','以后只发文字。','答复',request_id='same')
        self.assertEqual(len(first['entries']),len(second['entries']))
        b.scopes.remove('window-a',first['entries'][0]['id'])
        self.assertFalse(b.scopes.list('window-a')['entries'])
        self.assertFalse(b.dispatch(dict(op='query',args=dict(project='D:/project-a',session='session-a',question='答复习惯？')))['evidence'])
        with self.assertRaisesRegex(ValueError,'no_active_project'):b.scopes.add('unknown-window','project','项目要求。')

    def test_project_same_title_override_is_temporary_and_budgeted(self):
        b=self.bridge
        b.scopes.add('window-a','global','默认用中文答复。','输出语言',request_id='g')
        b.scopes.add('window-a','project','本项目使用英文答复。','输出语言',request_id='p')
        current=b.dispatch(dict(op='query',args=dict(project='D:/project-a',session='session-a',question='输出语言？')))
        self.assertTrue(any('英文' in r['value'] for r in current['evidence']))
        self.assertFalse(any('中文' in r['value'] for r in current['evidence']))
        self.assertLessEqual(current['packet_tokens'],b.core.config.memory_tokens)
        b.scopes.activate('window-a','D:/next-project','session-next')
        later=b.dispatch(dict(op='query',args=dict(project='D:/next-project',session='session-next',question='输出语言？')))
        self.assertTrue(any('中文' in r['value'] for r in later['evidence']))

    def test_first_turn_before_ui_activation_keeps_same_scope(self):
        b=self.bridge
        b.ingest('early-session','D:/early',[dict(id='u1',role='user',text='以后只发文字。')])
        before=b.scopes.project_for('early-session','D:/early')
        activation=b.scopes.activate('early-window','D:/early','early-session')
        self.assertEqual(activation['scope_key'],before)
        self.assertTrue(b.prepare_active('early-session','D:/early',['u1'])['batches'])


if __name__=='__main__':unittest.main()
