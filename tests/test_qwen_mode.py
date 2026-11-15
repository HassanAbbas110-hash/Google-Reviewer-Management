import unittest
from unittest.mock import patch
from reviewer.ai import Ollama


class QwenModeTests(unittest.TestCase):
    def payload(self,model):
        ai=Ollama(); sent={}
        class Reply:
            def raise_for_status(self): pass
            def json(self): return {'message':{'content':'{"risk":"routine","reason":"Praise","reply":"Glad we could help with your project!"}'}}
        def post(url,**kwargs): sent.update(kwargs['json']); return Reply()
        b={'name':'Shop','facts':'Tools','contact':'support@example.com','tone':'Warm','language':'English','model':model}
        with patch.object(ai,'models',return_value=[model]),patch.object(ai.session,'post',side_effect=post):
            ai.generate(b,{'comment':'Helpful staff','rating':5})
        return sent
    def test_qwen3_short_replies_disable_thinking(self):
        payload=self.payload('qwen3:4b')
        self.assertIs(payload.get('think'),False)
        self.assertFalse(payload['stream'])
    def test_other_models_do_not_receive_unsupported_thinking_flag(self):
        for model in ['llama3.2:3b','gemma3:4b']:
            with self.subTest(model=model): self.assertNotIn('think',self.payload(model))

if __name__=='__main__': unittest.main()
