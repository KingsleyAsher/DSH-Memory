import tempfile
import unittest
from memory_core.plugin_bridge import PluginBridge

class ChatStyleTests(unittest.TestCase):
    def test_style_is_project_scoped_and_not_a_user_fact(self):
        with tempfile.TemporaryDirectory() as directory:
            b=PluginBridge(directory)
            try:
                project='wechat-conversation:'+'a'*64
                other='wechat-conversation:'+'b'*64
                profile=dict(project=project,rules=[dict(scene='闲聊',member='',text='闲聊简短自然',confidence=.9,evidence=[dict(id='m1',quote='不要这么客套')])],processed=20,total=30)
                result=b.dispatch(dict(op='style_project_put',args=dict(project=project,profile=profile)))
                self.assertEqual(result['scope'],'project')
                b.scopes.activate('a',project)
                b.scopes.activate('b',other)
                rows=b.scopes.list('a')['entries']
                self.assertEqual(len(rows),1)
                self.assertEqual(rows[0]['origin'],'style-learning')
                self.assertFalse(b.scopes.list('b')['entries'])
                self.assertFalse(b.core.store.facts())
                b.scopes.remove('a',rows[0]['id'])
                self.assertIsNone(b.scopes.get_chat_style(project)['profile'])
                with self.assertRaisesRegex(ValueError,'invalid_conversation_scope'):
                    b.scopes.put_chat_style('@memory/global',profile)
            finally:b.close()
