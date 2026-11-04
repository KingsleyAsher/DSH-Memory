import unittest,tempfile
from memory_core.plugin_bridge import PluginBridge

class ExplicitTests(unittest.TestCase):
    def test_exact_request_idempotency_and_rejection(self):
        with tempfile.TemporaryDirectory() as home:
            b=PluginBridge(home)
            try:
                b.scopes.activate('w','D:/p','s')
                text='你好，以后我的录音笔记都要做成pdf笔记'
                b.ingest('s','D:/p',[dict(id='m',role='user',text=text)])
                b.ingest('s','D:/p',[dict(id='m',role='user',text=text)])
                rows=b.scopes.list('w')['entries'];self.assertEqual(len(rows),1);self.assertEqual(rows[0]['text'],text)
                self.assertEqual(rows[0]['origin'],'explicit')
                b.ingest('s','D:/p',[dict(id='n',role='user',text='比如说，请记住别人说的假设。')])
                self.assertEqual(len(b.scopes.list('w')['entries']),1)
            finally:b.close()
