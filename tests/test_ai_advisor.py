import json
import os
import unittest
from unittest.mock import patch

from trader.ai_advisor import AIAdvisor
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


if __name__ == "__main__":
    unittest.main()
