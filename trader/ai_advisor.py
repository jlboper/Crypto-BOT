from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request

from .config import AISettings
from .domain import AIReview, Signal


class AIAdvisor:
    """Constrained reviewer: it can only reject or reduce deterministic entries."""

    def __init__(self, settings: AISettings) -> None:
        self.settings = settings
        self.api_key = os.getenv("OPENAI_API_KEY", "")

    @property
    def available(self) -> bool:
        return self.settings.enabled and bool(self.api_key)

    def review(self, signal: Signal, btc_bullish: bool, portfolio_context: dict[str, float]) -> AIReview:
        if not self.available:
            if self.settings.fail_closed:
                return AIReview("REJECT", 1.0, 0.0, "AI unavailable; fail-closed policy")
            return AIReview("ALLOW", 0.0, 1.0, "AI unavailable; quantitative signal used")

        schema = {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["ALLOW", "REJECT", "REDUCE"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "risk_multiplier": {"type": "number", "minimum": 0, "maximum": 1},
                "reason": {"type": "string", "maxLength": 240},
            },
            "required": ["verdict", "confidence", "risk_multiplier", "reason"],
            "additionalProperties": False,
        }
        snapshot = {
            "signal": signal.to_dict(),
            "btc_regime_bullish": btc_bullish,
            "portfolio": portfolio_context,
        }
        payload = {
            "model": self.settings.model,
            "store": False,
            "max_output_tokens": self.settings.max_output_tokens,
            "reasoning": {"effort": "low"},
            "instructions": (
                "You are a conservative risk reviewer for a spot-only crypto swing bot. "
                "The deterministic engine already proposed a BUY. You may ALLOW, REJECT, or REDUCE only. "
                "Never create a trade, increase size, remove a stop, suggest leverage, or override portfolio limits. "
                "Reject inconsistent, overextended, illiquid-looking, or regime-conflicted setups."
            ),
            "input": json.dumps(snapshot, separators=(",", ":")),
            "text": {"format": {"type": "json_schema", "name": "trade_risk_review", "strict": True, "schema": schema}},
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
                body = json.loads(response.read().decode("utf-8"))
            text = body.get("output_text") or self._extract_output_text(body)
            parsed = json.loads(text)
            if body.get("status", "completed") != "completed" or not isinstance(parsed, dict):
                raise ValueError("incomplete response")
            verdict = parsed["verdict"]
            if verdict not in {"ALLOW", "REJECT", "REDUCE"} or not isinstance(parsed["reason"], str):
                raise ValueError("invalid review")
            confidence = parsed["confidence"]
            multiplier = parsed["risk_multiplier"]
            for value in (confidence, multiplier):
                if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError("invalid review number")
            if confidence < self.settings.minimum_confidence:
                return AIReview("REJECT", confidence, 0.0, "AI confidence below configured minimum")
            if verdict == "ALLOW":
                multiplier = min(1.0, multiplier)
            elif verdict == "REDUCE":
                multiplier = min(0.75, multiplier)
            else:
                multiplier = 0.0
            return AIReview(verdict, confidence, multiplier, str(parsed["reason"])[:240])
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError, AttributeError) as exc:
            if self.settings.fail_closed:
                return AIReview("REJECT", 1.0, 0.0, f"AI review failed safely: {type(exc).__name__}")
            return AIReview("ALLOW", 0.0, 1.0, f"AI review unavailable: {type(exc).__name__}")

    @staticmethod
    def _extract_output_text(body: dict) -> str:
        texts: list[str] = []
        for item in body.get("output", []):
            for content in item.get("content", []):
                if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                    texts.append(content["text"])
        if not texts:
            raise ValueError("OpenAI response contained no output text")
        return "".join(texts)
