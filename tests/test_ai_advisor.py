import json
import os
import unittest
from io import StringIO
from unittest.mock import patch

from trader.ai_advisor import AIAdvisor
from trader.cli import main
from trader.config import load_config
from trader.domain import Signal


class AIAdvisorTests(unittest.TestCase):
    def test_extracts_structured_output(self):
        expected={"verdict":"ALLOW","confidence":0.8,"risk_multiplier":1.0,"reason":"consistent"}
        body={"output":[{"content":[{"type":"output_text","text":json.dumps(expected)}]}]}
        self.assertEqual(json.loads(AIAdvisor._extract_output_text(body)),expected)

    def test_missing_key_fails_closed(self):
        config=load_config()
        signal=Signal("BTCUSDT","BUY",80,100.0,95.0,110.0,2.0,60.0,101.0,99.0,1.3,"test","now")
        with patch.dict(os.environ,{"OPENAI_API_KEY":""}):
            review=AIAdvisor(config.ai).review(signal,True,{})
        self.assertEqual(review.verdict,"REJECT")
        self.assertEqual(review.risk_multiplier,0.0)

    def test_model_probe_checks_access_without_any_order(self):
        result={"verdict":"REJECT","confidence":0.9,"risk_multiplier":0,"reason":"synthetic input"}
        with patch.dict(os.environ,{"OPENAI_API_KEY":"fake-for-tests"}), \
             patch("urllib.request.urlopen") as call, \
             patch("sys.argv",["trader","check-ai-model","--model","gpt-6-luna"]), \
             patch("sys.stdout",new_callable=StringIO) as output:
            call.return_value.__enter__.return_value.read.return_value=json.dumps({"output_text":json.dumps(result)}).encode()
            main()
            request=json.loads(call.call_args.args[0].data)
        self.assertEqual(request["model"],"gpt-6-luna")
        self.assertFalse(request["store"])
        self.assertEqual(json.loads(output.getvalue())["order_submission_enabled"],False)


if __name__ == "__main__":
    unittest.main()
