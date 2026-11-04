import tempfile,unittest
from memory_core.plugin_bridge import PluginBridge

class ReviewTests(unittest.TestCase):
    def test_review_stays_out_of_recall_until_accepted(self):
        with tempfile.TemporaryDirectory() as home:
            b=PluginBridge(home)
            try:
                b.scopes.activate('w','D:/p','s')
                b.ingest('s','D:/p',[dict(id='m',role='user',text='也许以后默认输出中文，但还没有决定。')])
                item=dict(session='s',title='输出语言',text='默认输出中文。',quote='也许以后默认输出中文，但还没有决定。',reason='用户尚未决定',confidence=.2)
                result=b.scopes.suggest(**item)
                self.assertEqual(b.scopes.list('w')['entries'],[])
                self.assertEqual(len(b.scopes.candidates('w')['candidates']),1)
                with self.assertRaises(ValueError):b.scopes.suggest(**dict(item,confidence=.8))
                with self.assertRaises(ValueError):b.scopes.resolve_candidate('foreign',result['candidate_id'],accept=True)
                b.scopes.resolve_candidate('w',result['candidate_id'],accept=True,text='默认输出英文。')
                self.assertEqual(b.scopes.list('w')['entries'][0]['text'],'默认输出英文。')
                self.assertEqual(b.scopes.candidates('w')['candidates'],[])
                rejected=b.scopes.suggest(**dict(item,text='以后用日语。'))
                b.scopes.resolve_candidate('w',rejected['candidate_id'],accept=False)
                self.assertEqual(len(b.scopes.list('w')['entries']),1)
                with self.assertRaises(ValueError):b.scopes.suggest(**dict(item,quote='不存在的用户原话'))
            finally:b.close()
