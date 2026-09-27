"""Multi-asset USDⓈ-M Futures Demo forward-test engine.

Runs beside Spot Testnet with separate positions per configured symbol, a single
durable order journal, isolated 1x execution, full signal history, and shadow
strategy simulation. LIVE is not implemented.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from .domain import Candle
from .ai_advisor import AIAdvisor
from .futures_testnet import FuturesTestnetLab, FuturesTestnetExecutionError, _decimal
from .indicators import atr, ema_series, rsi, sma


class FuturesForwardEngine:
    def __init__(self, config, exchange):
        self.config=config; self.settings=config.futures_testnet; self.exchange=exchange
        self.lab=FuturesTestnetLab(self.settings); self.ledger=self.lab.ledger; self.ai=AIAdvisor(config.ai)

    @property
    def symbols(self): return self.settings.forward_symbols

    def killed(self)->bool: return self.settings.kill_switch_path.exists()

    def _halt(self,reason:str,*,overwrite_last_error:bool=True)->None:
        self.settings.kill_switch_path.parent.mkdir(parents=True,exist_ok=True)
        if not self.settings.kill_switch_path.exists():
            self.settings.kill_switch_path.write_text(str(reason)[:200]+"\n",encoding="utf-8")
        if overwrite_last_error:
            self.ledger.set_setting("forward_last_error",{"message":str(reason)[:200],"at":datetime.now(UTC).isoformat()})

    def _signal(self,candles:list[Candle])->dict:
        s=self.config.strategy
        required=max(s.ema_slow+5,s.breakout_period+2,s.atr_period+2,s.volume_period+2)
        if len(candles)<required: raise ValueError("Futures forward history unavailable")
        closes=[c.close for c in candles]; highs=[c.high for c in candles]; lows=[c.low for c in candles]; volumes=[c.volume for c in candles]
        price=closes[-1]; fast_series=ema_series(closes,s.ema_fast); slow_series=ema_series(closes,s.ema_slow)
        fast=fast_series[-1]; slow=slow_series[-1]; current_rsi=rsi(closes,s.rsi_period)
        current_atr=atr(highs,lows,closes,s.atr_period); avg=sma(volumes[:-1],s.volume_period)
        volume_ratio=volumes[-1]/avg if avg>0 else 0.0
        prior_high=max(highs[-s.breakout_period-1:-1]); prior_low=min(lows[-s.breakout_period-1:-1])
        momentum=(price/closes[-6])-1.0
        long_score=0; short_score=0
        if price>fast>slow: long_score+=25
        if price<fast<slow: short_score+=25
        if len(fast_series)>=4 and fast_series[-1]>fast_series[-4]: long_score+=10
        if len(fast_series)>=4 and fast_series[-1]<fast_series[-4]: short_score+=10
        if 52<=current_rsi<=72: long_score+=15
        elif 48<=current_rsi<52: long_score+=7
        if 28<=current_rsi<=48: short_score+=15
        elif 48<current_rsi<=52: short_score+=7
        if volume_ratio>=1.2: long_score+=15; short_score+=15
        elif volume_ratio>=1.0: long_score+=8; short_score+=8
        if price>prior_high: long_score+=20
        if price<prior_low: short_score+=20
        if momentum>=0.01: long_score+=15
        if momentum<=-0.01: short_score+=15
        if current_atr/price>0.12: long_score-=15; short_score-=15
        long_score=max(0,min(100,long_score)); short_score=max(0,min(100,short_score)); score=max(long_score,short_score)
        direction=None
        if score>=self.settings.forward_min_score and abs(long_score-short_score)>=10:
            direction="LONG" if long_score>short_score else "SHORT"
        return {"direction":direction,"score":score,"long_score":long_score,"short_score":short_score,
                "price":price,"atr":current_atr,"rsi":current_rsi,"ema_fast":fast,"ema_slow":slow,"volume_ratio":volume_ratio}

    @staticmethod
    def _shadow_variants()->list[dict]:
        return [{"key":f"s{score}-a{atr_mult}-rr{rr}","score":score,"atr_mult":atr_mult,"rr":rr}
                for score in (70,75,80) for atr_mult in (1.5,2.0,2.5) for rr in (1.5,2.0,2.5)]

    def _actual_rows(self,symbol:str)->list[dict]: return self.lab._position_rows(symbol)

    def _validated_rows(self, symbol: str, local: dict | None) -> list[dict]:
        rows = self._actual_rows(symbol)
        if local is not None and len(rows) == 1:
            rows = [self.lab.ensure_forward_position_configuration(symbol, rows[0])]
        self._assert_consistent(symbol, local, rows)
        return rows

    def _record_account(self)->dict:
        account=self.lab._account(); wallet=float(_decimal(account.get("totalWalletBalance","0")))
        available=float(_decimal(account.get("availableBalance","0"))); unrealized=0.0
        for symbol in self.symbols:
            unrealized+=sum(float(_decimal(r.get("unRealizedProfit","0"))) for r in self._actual_rows(symbol))
        self.ledger.record_forward_equity(wallet,available,unrealized)
        return {"wallet_balance":wallet,"available_balance":available,"unrealized_pnl":unrealized}

    def _assert_consistent(self,symbol:str,local:dict|None,rows:list[dict])->None:
        if local is None and rows: raise FuturesTestnetExecutionError(f"Untracked Futures Demo position: {symbol}")
        if local is None: return
        if len(rows)!=1: raise FuturesTestnetExecutionError(f"Tracked Futures position missing or ambiguous: {symbol}")
        amount=_decimal(rows[0].get("positionAmt","0")); expected=1 if local["direction"]=="LONG" else -1; actual=1 if amount>0 else -1
        if actual!=expected or abs(float(abs(amount))-float(local["quantity"]))>1e-12:
            raise FuturesTestnetExecutionError(f"Futures forward position identity mismatch: {symbol}")
        if int(float(rows[0].get("leverage",0) or 0))!=1: raise FuturesTestnetExecutionError("Automatic Futures leverage changed from 1x")
        if str(rows[0].get("marginType","")).lower()!="isolated": raise FuturesTestnetExecutionError("Automatic Futures margin is not isolated")

    def _close(self,local:dict,reason:str)->dict:
        symbol=local["symbol"]; rows=self._validated_rows(symbol, local)
        amount=_decimal(rows[0]["positionAmt"]); side="SELL" if amount>0 else "BUY"
        order=self.lab.forward_submit(symbol=symbol,side=side,quantity=abs(amount),reduce_only=True)
        if self._actual_rows(symbol): raise FuturesTestnetExecutionError(f"Futures forward close left open position: {symbol}")
        exit_price=self.lab._execution_price(order,symbol); entry=_decimal(local["entry_price"]); qty=_decimal(local["quantity"])
        pnl=(exit_price-entry)*qty if local["direction"]=="LONG" else (entry-exit_price)*qty
        closed=self.ledger.close_forward_position(symbol=symbol,exit_price=float(exit_price),gross_pnl=float(pnl),exit_reason=reason)
        self.ledger.set_setting("forward_pending_order",None); return closed

    def _recover_journal(self)->dict|None:
        pending_before=self.ledger.setting("forward_pending_order")
        if not pending_before: return None
        outcome=self.lab.reconcile_forward_pending()
        if not outcome or not outcome.get("resolved"): return outcome
        symbol=str(pending_before["symbol"])
        if outcome.get("status")!="FILLED":
            self.ledger.set_setting("forward_open_plan",None); return outcome
        pending=outcome["pending"]; order=outcome["order"]; local=self.ledger.forward_position(symbol); rows=self._actual_rows(symbol)
        if pending.get("reduce_only"):
            if local is not None and not rows:
                exit_price=self.lab._execution_price(order,symbol); entry=_decimal(local["entry_price"]); qty=_decimal(local["quantity"])
                pnl=(exit_price-entry)*qty if local["direction"]=="LONG" else (entry-exit_price)*qty
                closed=self.ledger.close_forward_position(symbol=symbol,exit_price=float(exit_price),gross_pnl=float(pnl),exit_reason="RECOVERED_CLOSE")
                self.ledger.set_setting("forward_pending_order",None)
                return {"resolved":True,"status":"RECOVERED_CLOSE","trade":closed}
            if local is not None: rows=self._validated_rows(symbol, local)
            return outcome
        if local is None:
            plan=self.ledger.setting("forward_open_plan")
            if not isinstance(plan,dict) or plan.get("symbol")!=symbol or len(rows)!=1:
                self._halt("uncertain Futures open could not be reconstructed"); raise FuturesTestnetExecutionError("Futures forward recovery requires owner review")
            row=self.lab.ensure_forward_position_configuration(symbol, rows[0]); amount=_decimal(row.get("positionAmt","0")); direction=str(plan["direction"])
            if (direction=="LONG" and amount<=0) or (direction=="SHORT" and amount>=0): raise FuturesTestnetExecutionError("Recovered Futures direction mismatch")
            entry=_decimal(row.get("entryPrice","0"))
            if entry<=0: entry=self.lab._execution_price(order,symbol)
            distance=max(Decimal(str(self.settings.forward_stop_atr_multiple*float(plan["atr"]))),Decimal(str(self.settings.forward_minimum_stop_pct))*entry)
            stop=entry-distance if direction=="LONG" else entry+distance
            take=entry+Decimal(str(self.settings.forward_reward_to_risk))*distance if direction=="LONG" else entry-Decimal(str(self.settings.forward_reward_to_risk))*distance
            liquidation=_decimal(row.get("liquidationPrice","0"))
            reconstructed={"symbol":symbol,"direction":direction,"leverage":1,"quantity":float(abs(amount)),"entry_price":float(entry),
                "stop_price":float(stop),"take_profit":float(take),"liquidation_price":float(liquidation) if liquidation>0 else None,
                "signal_score":int(plan["score"]),"opened_at":str(plan["opened_at"])}
            self.ledger.set_forward_position(reconstructed); self.ledger.set_setting("forward_open_plan",None); self.ledger.set_setting("forward_pending_order",None)
            return {"resolved":True,"status":"RECOVERED_OPEN","position":reconstructed}
        rows=self._validated_rows(symbol, local); self.ledger.set_setting("forward_open_plan",None); self.ledger.set_setting("forward_pending_order",None)
        return outcome

    def protection_tick(self)->dict:
        if not self.settings.forward_enabled: return {"enabled":False}
        pending=self._recover_journal()
        if pending and not pending.get("resolved"): return {"enabled":True,"status":"PENDING_RECONCILIATION"}
        closed=[]
        for local in self.ledger.forward_positions():
            symbol=local["symbol"]
            try: rows=self._validated_rows(symbol, local)
            except Exception as exc:self._halt(str(exc)); raise
            mark=_decimal(rows[0].get("markPrice","0"))
            if mark<=0: raise FuturesTestnetExecutionError("Futures mark price unavailable")
            hit=(local["direction"]=="LONG" and (mark<=_decimal(local["stop_price"]) or mark>=_decimal(local["take_profit"]))) or (
                 local["direction"]=="SHORT" and (mark>=_decimal(local["stop_price"]) or mark<=_decimal(local["take_profit"])))
            if hit:
                reason="STOP" if ((local["direction"]=="LONG" and mark<=_decimal(local["stop_price"])) or (local["direction"]=="SHORT" and mark>=_decimal(local["stop_price"]))) else "TAKE_PROFIT"
                closed.append(self._close(local,reason))
        return {"enabled":True,"status":"CLOSED" if closed else ("OPEN" if self.ledger.forward_positions() else "FLAT"),"closed":closed}

    def cycle_symbol(self,symbol:str,candles:list[Candle],account:dict)->dict:
        local=self.ledger.forward_position(symbol); rows=self._validated_rows(symbol, local)
        signal=self._signal(candles); self.ledger.record_signal(symbol,signal)
        self.ledger.set_setting(f"forward_last_signal_{symbol}",{**signal,"at":datetime.now(UTC).isoformat()})
        self.ledger.shadow_step(symbol,signal,self._shadow_variants())
        if local:
            opposite=(local["direction"]=="LONG" and signal["short_score"]>=self.settings.forward_min_score) or (local["direction"]=="SHORT" and signal["long_score"]>=self.settings.forward_min_score)
            if opposite:return {"symbol":symbol,"status":"CLOSED","trade":self._close(local,"OPPOSITE_SIGNAL"),"signal":signal}
            return {"symbol":symbol,"status":"OPEN","position":local,"signal":signal}
        if signal["direction"] is None:return {"symbol":symbol,"status":"FLAT","signal":signal}
        if len(self.ledger.forward_positions())>=self.settings.forward_max_positions:return {"symbol":symbol,"status":"POSITION_LIMIT","signal":signal}
        ai_review=self.ai.review_futures(signal,{"wallet_balance":float(account["wallet_balance"]),"available_balance":float(account["available_balance"]),
            "unrealized_pnl":float(account["unrealized_pnl"]),"open_positions":float(len(self.ledger.forward_positions())),"automatic_leverage":1.0})
        review={"model":self.config.ai.model,"verdict":ai_review.verdict,"confidence":ai_review.confidence,"reason":ai_review.reason,
                "direction":signal["direction"],"score":int(signal["score"]),"at":datetime.now(UTC).isoformat()}
        self.ledger.set_setting(f"forward_last_ai_review_{symbol}",review)
        if ai_review.verdict!="ALLOW" or ai_review.risk_multiplier<=0:return {"symbol":symbol,"status":"AI_REJECTED","signal":signal,"ai_review":review}
        quantity=self.lab._validate_smoke_quantity(symbol,signal["direction"]); estimated=_decimal(signal["price"])*quantity
        budget=Decimal(str(self.settings.forward_margin_usdt))
        if estimated>budget*Decimal("1.25"): raise FuturesTestnetExecutionError(f"{symbol} minimum quantity exceeds Futures forward budget")
        if _decimal(account["available_balance"])<max(budget,estimated)*Decimal("1.25"): raise FuturesTestnetExecutionError("Insufficient Futures Demo margin")
        side="BUY" if signal["direction"]=="LONG" else "SELL"
        plan={"symbol":symbol,"direction":signal["direction"],"score":int(signal["score"]),"atr":float(signal["atr"]),"opened_at":datetime.now(UTC).isoformat()}
        self.ledger.set_setting("forward_open_plan",plan)
        order=self.lab.forward_submit(symbol=symbol,side=side,quantity=quantity,reduce_only=False)
        rows=self._actual_rows(symbol)
        if len(rows)!=1: raise FuturesTestnetExecutionError(f"Futures forward open position not found: {symbol}")
        row=self.lab.ensure_forward_position_configuration(symbol, rows[0])
        amount=_decimal(row["positionAmt"]); actual_qty=abs(amount); entry=_decimal(row.get("entryPrice",order.get("avgPrice","0")))
        if entry<=0: entry=self.lab._execution_price(order,symbol)
        distance=max(Decimal(str(self.settings.forward_stop_atr_multiple*signal["atr"])),Decimal(str(self.settings.forward_minimum_stop_pct))*entry)
        direction=signal["direction"]; stop=entry-distance if direction=="LONG" else entry+distance
        take=entry+Decimal(str(self.settings.forward_reward_to_risk))*distance if direction=="LONG" else entry-Decimal(str(self.settings.forward_reward_to_risk))*distance
        liquidation=_decimal(row.get("liquidationPrice","0"))
        position={"symbol":symbol,"direction":direction,"leverage":1,"quantity":float(actual_qty),"entry_price":float(entry),"stop_price":float(stop),
            "take_profit":float(take),"liquidation_price":float(liquidation) if liquidation>0 else None,"signal_score":int(signal["score"]),"opened_at":plan["opened_at"]}
        self.ledger.set_forward_position(position); self.ledger.set_setting("forward_open_plan",None); self.ledger.set_setting("forward_pending_order",None)
        return {"symbol":symbol,"status":"OPENED","position":position,"signal":signal,"ai_review":review}

    def cycle(self,candle_map:dict[str,list[Candle]])->dict:
        if not self.settings.forward_enabled:return {"enabled":False,"status":"OFF"}
        if self.killed():return {"enabled":True,"status":"KILLED"}
        pending=self._recover_journal()
        if pending and not pending.get("resolved"):return {"enabled":True,"status":"PENDING_RECONCILIATION"}
        account=self._record_account(); results=[]
        for symbol in self.symbols:
            candles=candle_map.get(symbol)
            if not candles: results.append({"symbol":symbol,"status":"NO_DATA"}); continue
            results.append(self.cycle_symbol(symbol,candles,account))
        return {"enabled":True,"status":"ACTIVE","results":results,**account}

    def snapshot(self)->dict:
        data=self.ledger.forward_snapshot()
        return {"enabled":self.settings.forward_enabled,"killed":self.killed(),"symbols":list(self.symbols),
            "automatic_leverage":1,"latest_signals":{s:self.ledger.setting(f"forward_last_signal_{s}") for s in self.symbols},
            "last_error":self.ledger.setting("forward_last_error"),"ai_model":self.config.ai.model,
            "last_ai_reviews":{s:self.ledger.setting(f"forward_last_ai_review_{s}") for s in self.symbols},
            "recovery":{"durable_order_journal":True,"startup_position_reconciliation":True,"separate_kill_switch":True,
                        "native_exchange_stop_orders":False},**data}
