"""Multi-asset USDⓈ-M Futures Demo forward-test engine.

Runs beside Spot Testnet with separate positions per configured symbol, a single
durable order journal, isolated bounded Demo leverage, full signal history, and shadow
strategy simulation. LIVE is not implemented.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .domain import Candle
from .ai_advisor import AIAdvisor
from .futures_testnet import FuturesTestnetLab, FuturesTestnetExecutionError, _decimal
from .indicators import atr, ema_series, rsi, sma
from .native_protection import FuturesNativeProtection, FUTURES_KEY, projection

FUTURES_LEVERAGE_TRIAL_PROTOCOL = 1


class FuturesForwardEngine:
    def __init__(self, config, exchange):
        self.config=config; self.settings=config.futures_testnet; self.exchange=exchange
        self.lab=FuturesTestnetLab(self.settings); self.ledger=self.lab.ledger; self.ai=AIAdvisor(config.ai)
        self.native = FuturesNativeProtection(self)
        if len(self.settings.forward_leverage_trials) > 1 and not self.ledger.setting("forward_leverage_trials_started_at"):
            self.ledger.set_setting("forward_leverage_trials_started_at", datetime.now(UTC).isoformat())

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
        return [{"key":f"v2-s{score}-a{atr_mult}-rr{rr}","score":score,"atr_mult":atr_mult,"rr":rr}
                for score in (70,75,80) for atr_mult in (1.5,2.0,2.5) for rr in (1.5,2.0,2.5)]

    def _actual_rows(self,symbol:str)->list[dict]: return self.lab._position_rows(symbol)

    def _validated_rows(self, symbol: str, local: dict | None) -> list[dict]:
        rows = self._actual_rows(symbol)
        if local is not None and len(rows) == 1:
            self._assert_identity(symbol, local, rows)
            rows = [self.lab.ensure_forward_position_configuration(symbol, rows[0], int(local["leverage"]))]
        self._assert_consistent(symbol, local, rows)
        return rows

    def _record_account(self)->dict:
        account=self.lab._account(); wallet=float(_decimal(account.get("totalWalletBalance","0")))
        available=float(_decimal(account.get("availableBalance","0"))); unrealized=0.0
        for symbol in self.symbols:
            unrealized+=sum(float(_decimal(r.get("unRealizedProfit","0"))) for r in self._actual_rows(symbol))
        self.ledger.record_forward_equity(wallet,available,unrealized)
        return {"wallet_balance":wallet,"available_balance":available,"unrealized_pnl":unrealized}

    def _assert_identity(self,symbol:str,local:dict|None,rows:list[dict])->None:
        if local is None and rows: raise FuturesTestnetExecutionError(f"Untracked Futures Demo position: {symbol}")
        if local is None: return
        if len(rows)!=1: raise FuturesTestnetExecutionError(f"Tracked Futures position missing or ambiguous: {symbol}")
        amount=_decimal(rows[0].get("positionAmt","0")); expected=1 if local["direction"]=="LONG" else -1; actual=1 if amount>0 else -1
        if actual!=expected or abs(float(abs(amount))-float(local["quantity"]))>1e-12:
            raise FuturesTestnetExecutionError(f"Futures forward position identity mismatch: {symbol}")
        position_side=str(rows[0].get("positionSide","")).upper()
        if position_side and position_side!="BOTH":
            raise FuturesTestnetExecutionError("Automatic Futures position mode changed from ONE_WAY")

    def _assert_consistent(self,symbol:str,local:dict|None,rows:list[dict])->None:
        self._assert_identity(symbol,local,rows)
        if local is None:return
        if int(local['leverage']) not in {1, 2, 3} or int(float(rows[0].get("leverage",0) or 0)) != int(local['leverage']):
            raise FuturesTestnetExecutionError("Automatic Futures leverage differs from durable position")
        if str(rows[0].get("marginType","")).lower()!="isolated": raise FuturesTestnetExecutionError("Automatic Futures margin is not isolated")

    def _repair_cross_position(self,local:dict,row:dict)->dict:
        symbol=local["symbol"]
        self._assert_identity(symbol,local,[row])
        if str(row.get("marginType","")).lower() not in {"cross", "crossed"}:
            raise FuturesTestnetExecutionError("Futures CROSS configuration is not confirmed")
        native_trade = self.native.reconcile(symbol, cancel=True)
        if native_trade:
            self.lab.ensure_flat_forward_configuration(symbol)
            return native_trade
        amount=_decimal(row["positionAmt"]); side="SELL" if amount>0 else "BUY"
        order=self.lab.forward_submit(symbol=symbol,side=side,quantity=abs(amount),reduce_only=True)
        if self._actual_rows(symbol):
            raise FuturesTestnetExecutionError(f"Futures configuration repair left open position: {symbol}")
        exit_price=self.lab._execution_price(order,symbol); entry=_decimal(local["entry_price"]); qty=_decimal(local["quantity"])
        pnl=(exit_price-entry)*qty if local["direction"]=="LONG" else (entry-exit_price)*qty
        closed=self.ledger.close_forward_position(symbol=symbol,exit_price=float(exit_price),gross_pnl=float(pnl),exit_reason="CONFIG_REPAIR")
        self.ledger.set_setting("forward_pending_order",None)
        self.lab.ensure_flat_forward_configuration(symbol)
        self.ledger.set_setting("forward_last_config_repair",{"symbol":symbol,"reason":"margin_not_isolated","at":datetime.now(UTC).isoformat()})
        return closed

    def _preflight_flat_symbols(self)->dict[str,dict]:
        """Repair harmless flat-symbol drift without taking the whole motor down."""
        health={}
        local_symbols={row["symbol"] for row in self.ledger.forward_positions()}
        for symbol in self.symbols:
            if symbol in local_symbols:
                health[symbol]={"status":"OPEN","at":datetime.now(UTC).isoformat()}
                continue
            try:
                if self._actual_rows(symbol):
                    raise FuturesTestnetExecutionError(f"Untracked Futures Demo position: {symbol}")
                state=self.lab.ensure_flat_forward_configuration(symbol)
                health[symbol]={"status":"READY","margin_type":str(state.get("marginType","")).upper(),
                                "leverage":int(float(state.get("leverage",0) or 0)),
                                "at":datetime.now(UTC).isoformat()}
            except Exception as exc:
                health[symbol]={"status":"BLOCKED","error":(type(exc).__name__+": "+str(exc))[:180],
                                "at":datetime.now(UTC).isoformat()}
        self.ledger.set_setting("forward_symbol_health",health)
        return health

    def _automatic_pause_reason(self)->str|None:
        if not self.killed(): return None
        try: reason=self.settings.kill_switch_path.read_text(encoding="utf-8",errors="replace").strip().lower()
        except OSError:return None
        return reason if reason.startswith("three consecutive futures ") else None

    def _attempt_auto_recovery(self)->bool:
        """Auto-resume only automatic error pauses after full safe reconciliation."""
        if not self._automatic_pause_reason(): return False
        try:
            # A previous confirmed write may have left only the durable journal
            # behind. Reconcile it before deciding that recovery is blocked.
            pending=self._recover_journal()
            if pending and not pending.get("resolved"):
                return False
            # Existing tracked exposure must be reconciled first. CROSS is safely
            # flattened by the same identity-first repair used by protection_tick.
            for local in list(self.ledger.forward_positions()):
                rows=self._actual_rows(local["symbol"])
                self._assert_identity(local["symbol"],local,rows)
                if str(rows[0].get("marginType","")).lower()!="isolated":
                    self._repair_cross_position(local,rows[0])
                else:
                    self._validated_rows(local["symbol"],local)
                    self.native.ensure(local)
            health=self._preflight_flat_symbols()
            if any(row.get("status")=="BLOCKED" for row in health.values()):
                return False
            self._record_account()
        except Exception as exc:
            self.ledger.set_setting("forward_last_recovery_error",{
                "message":(type(exc).__name__+": "+str(exc))[:200],
                "at":datetime.now(UTC).isoformat(),
            })
            return False
        try:self.settings.kill_switch_path.unlink()
        except FileNotFoundError:pass
        self.ledger.set_setting("forward_cycle_consecutive_errors",0)
        self.ledger.set_setting("forward_protection_consecutive_errors",0)
        self.ledger.set_setting("forward_consecutive_errors",0)
        self.ledger.set_setting("forward_last_auto_recovery",{"status":"RESUMED","at":datetime.now(UTC).isoformat()})
        return True

    def safe_resume(self)->dict:
        """Resume a paused forward motor only after a full exchange-backed audit."""
        if not self.killed():
            return {"status":"ALREADY_ACTIVE","resumed":False}
        pending=self._recover_journal()
        if pending and not pending.get("resolved"):
            raise FuturesTestnetExecutionError("Futures safe resume blocked by pending reconciliation")
        for local in list(self.ledger.forward_positions()):
            rows=self._actual_rows(local["symbol"])
            self._assert_identity(local["symbol"],local,rows)
            if str(rows[0].get("marginType","")).lower()!="isolated":
                self._repair_cross_position(local,rows[0])
            else:
                self._validated_rows(local["symbol"],local)
                self.native.ensure(local)
        health=self._preflight_flat_symbols()
        blocked={symbol:row for symbol,row in health.items() if row.get("status")=="BLOCKED"}
        if blocked:
            detail="; ".join(f"{symbol}: {row.get('error','blocked')}" for symbol,row in blocked.items())
            raise FuturesTestnetExecutionError(("Futures safe resume blocked by symbol preflight · "+detail)[:500])
        self._record_account()
        try:self.settings.kill_switch_path.unlink()
        except FileNotFoundError:pass
        self.ledger.set_setting("forward_cycle_consecutive_errors",0)
        self.ledger.set_setting("forward_protection_consecutive_errors",0)
        self.ledger.set_setting("forward_consecutive_errors",0)
        result={"status":"RESUMED","resumed":True,"at":datetime.now(UTC).isoformat()}
        self.ledger.set_setting("forward_last_auto_recovery",result)
        return result

    def _close(self,local:dict,reason:str)->dict:
        symbol=local["symbol"]
        native_trade = self.native.reconcile(symbol)
        if native_trade: return native_trade
        self._validated_rows(symbol, local)
        native_trade = self.native.reconcile(symbol, cancel=True)
        if native_trade: return native_trade
        rows=self._validated_rows(symbol, local)
        amount=_decimal(rows[0]["positionAmt"]); side="SELL" if amount>0 else "BUY"
        order=self.lab.forward_submit(symbol=symbol,side=side,quantity=abs(amount),reduce_only=True)
        if self._actual_rows(symbol): raise FuturesTestnetExecutionError(f"Futures forward close left open position: {symbol}")
        exit_price=self.lab._execution_price(order,symbol); entry=_decimal(local["entry_price"]); qty=_decimal(local["quantity"])
        pnl=(exit_price-entry)*qty if local["direction"]=="LONG" else (entry-exit_price)*qty
        closed=self.ledger.close_forward_position(symbol=symbol,exit_price=float(exit_price),gross_pnl=float(pnl),exit_reason=reason)
        self.ledger.set_setting("forward_pending_order",None); return closed

    def _mark_evidence_gap(self, status: str, symbol: str, detail: str) -> None:
        self.ledger.set_setting("forward_evidence_gap", {
            "status": status,
            "symbol": symbol,
            "detail": str(detail)[:180],
            "at": datetime.now(UTC).isoformat(),
        })

    def _reconstruct_open_position(self, symbol: str, pending: dict, plan: dict, row: dict, order: dict | None = None) -> dict:
        direction=str(plan.get("direction",""))
        amount=_decimal(row.get("positionAmt","0"))
        expected=1 if direction=="LONG" else -1 if direction=="SHORT" else 0
        actual=1 if amount>0 else -1 if amount<0 else 0
        if expected==0 or actual!=expected:
            raise FuturesTestnetExecutionError("Recovered Futures direction mismatch")
        pending_qty=_decimal(pending.get("quantity","0"))
        if pending_qty<=0 or abs(float(abs(amount))-float(pending_qty))>1e-12:
            raise FuturesTestnetExecutionError("Recovered Futures quantity mismatch")
        position_side=str(row.get("positionSide","")).upper()
        if position_side and position_side!="BOTH":
            raise FuturesTestnetExecutionError("Automatic Futures position mode changed from ONE_WAY")
        entry=_decimal(row.get("entryPrice","0"))
        if entry<=0 and order is not None:
            entry=self.lab._execution_price(order,symbol)
        if entry<=0:
            raise FuturesTestnetExecutionError("Recovered Futures entry price unavailable")
        atr_value=float(plan.get("atr",0) or 0)
        if atr_value<=0:
            raise FuturesTestnetExecutionError("Recovered Futures ATR unavailable")
        distance=max(Decimal(str(self.settings.forward_stop_atr_multiple*atr_value)),
                     Decimal(str(self.settings.forward_minimum_stop_pct))*entry)
        stop=entry-distance if direction=="LONG" else entry+distance
        take=entry+Decimal(str(self.settings.forward_reward_to_risk))*distance if direction=="LONG" else entry-Decimal(str(self.settings.forward_reward_to_risk))*distance
        liquidation=_decimal(row.get("liquidationPrice","0"))
        leverage = plan.get("leverage", 1)
        if type(leverage) is not int or leverage not in {1, 2, 3} or leverage > self.settings.max_leverage:
            raise FuturesTestnetExecutionError("Recovered Futures leverage plan is invalid")
        return {"symbol":symbol,"direction":direction,"leverage":leverage,"quantity":float(abs(amount)),
                **({"leverage_trial_index": plan["leverage_trial_index"]} if "leverage_trial_index" in plan else {}),
                "entry_price":float(entry),"stop_price":float(stop),"take_profit":float(take),
                "liquidation_price":float(liquidation) if liquidation>0 else None,
                "signal_score":int(plan.get("score",0) or 0),"opened_at":str(plan.get("opened_at") or datetime.now(UTC).isoformat())}

    def _recover_journal(self)->dict|None:
        self.native.reconcile_all()
        pending=self.ledger.setting("forward_pending_order")
        if not pending:
            return None
        symbol=str(pending.get("symbol") or "")
        if symbol not in self.symbols:
            raise FuturesTestnetExecutionError("Futures forward journal symbol is invalid")
        local=self.ledger.forward_position(symbol)
        rows=self._actual_rows(symbol)
        reduce_only=bool(pending.get("reduce_only"))
        plan=self.ledger.setting("forward_open_plan")

        # A reduce-only close cannot create exposure. Current local + exchange
        # flatness is authoritative enough to remove stale bookkeeping even if
        # Binance no longer retains the historical order lookup.
        if reduce_only and local is None and not rows:
            self.ledger.set_setting("forward_open_plan",None)
            self.ledger.set_setting("forward_pending_order",None)
            self.ledger.set_setting("forward_last_journal_recovery",{
                "status":"CLEARED_FLAT_REDUCE_ONLY","symbol":symbol,"at":datetime.now(UTC).isoformat()})
            return {"resolved":True,"status":"RECOVERED_CLOSE_ALREADY_FLAT"}

        # Local accounting is only created after a confirmed open fill. If it
        # exists while the OPEN journal remains, this is a crash-window journal.
        # Verify current exchange identity, clear the stale open journal, then
        # repair configuration if needed.
        if not reduce_only and local is not None:
            self._assert_identity(symbol,local,rows)
            self.ledger.set_setting("forward_open_plan",None)
            self.ledger.set_setting("forward_pending_order",None)
            if str(rows[0].get("marginType","")).lower()!="isolated":
                closed=self._repair_cross_position(local,rows[0])
                self.ledger.set_setting("forward_last_journal_recovery",{
                    "status":"RECOVERED_TRACKED_OPEN_CROSS_CLOSED","symbol":symbol,"at":datetime.now(UTC).isoformat()})
                return {"resolved":True,"status":"RECOVERED_OPEN_CROSS_CLOSED","trade":closed}
            self._validated_rows(symbol,local)
            self.ledger.set_setting("forward_last_journal_recovery",{
                "status":"CLEARED_CONFIRMED_OPEN_JOURNAL","symbol":symbol,"at":datetime.now(UTC).isoformat()})
            return {"resolved":True,"status":"RECOVERED_OPEN","position":local}

        # If an OPEN journal has no local position but Binance has exactly one
        # matching exposure, the exchange itself proves the fill survived the
        # crash. Reconstruct local accounting before clearing the old journal.
        if not reduce_only and local is None and rows:
            if not isinstance(plan,dict) or plan.get("symbol")!=symbol or len(rows)!=1:
                self._halt("uncertain Futures open could not be reconstructed")
                raise FuturesTestnetExecutionError("Futures forward recovery requires owner review")
            reconstructed=self._reconstruct_open_position(symbol,pending,plan,rows[0])
            self.ledger.set_forward_position(reconstructed)
            self.ledger.set_setting("forward_open_plan",None)
            self.ledger.set_setting("forward_pending_order",None)
            if str(rows[0].get("marginType","")).lower()!="isolated":
                closed=self._repair_cross_position(reconstructed,rows[0])
                self.ledger.set_setting("forward_last_journal_recovery",{
                    "status":"RECOVERED_UNTRACKED_OPEN_CROSS_CLOSED","symbol":symbol,"at":datetime.now(UTC).isoformat()})
                return {"resolved":True,"status":"RECOVERED_OPEN_CROSS_CLOSED","trade":closed}
            refreshed=self.lab.ensure_forward_position_configuration(symbol,rows[0], int(reconstructed['leverage']))
            self._assert_identity(symbol,reconstructed,[refreshed])
            self.ledger.set_setting("forward_last_journal_recovery",{
                "status":"RECONSTRUCTED_CONFIRMED_OPEN","symbol":symbol,"at":datetime.now(UTC).isoformat()})
            return {"resolved":True,"status":"RECOVERED_OPEN","position":reconstructed}

        outcome=self.lab.reconcile_forward_pending()
        if not outcome:
            return None

        # Binance Demo may forget an old client-order lookup. Current flatness
        # still lets us recover an OPEN journal safely, but the historical fill
        # outcome is unknown, so preserve an explicit evidence warning.
        if outcome.get("status")=="ORDER_NOT_FOUND":
            if not reduce_only and local is None and not rows:
                self._mark_evidence_gap("ORPHANED_OPEN_FLAT",symbol,"Historical Binance order lookup expired while current exposure is zero")
                self.ledger.set_setting("forward_open_plan",None)
                self.ledger.set_setting("forward_pending_order",None)
                self.ledger.set_setting("forward_last_journal_recovery",{
                    "status":"QUARANTINED_ORPHANED_OPEN_FLAT","symbol":symbol,"at":datetime.now(UTC).isoformat()})
                return {"resolved":True,"status":"QUARANTINED_ORPHANED_OPEN_FLAT"}
            return outcome

        if not outcome.get("resolved"):
            return outcome
        if outcome.get("status")!="FILLED":
            self.ledger.set_setting("forward_open_plan",None)
            return outcome

        order=outcome["order"]
        local=self.ledger.forward_position(symbol)
        rows=self._actual_rows(symbol)
        if reduce_only:
            if local is None:
                if rows:
                    raise FuturesTestnetExecutionError(f"Futures close recovery found untracked exposure: {symbol}")
                self.ledger.set_setting("forward_open_plan",None)
                self.ledger.set_setting("forward_pending_order",None)
                self.ledger.set_setting("forward_last_journal_recovery",{
                    "status":"CONFIRMED_CLOSE_ALREADY_FLAT","symbol":symbol,"at":datetime.now(UTC).isoformat()})
                return {"resolved":True,"status":"RECOVERED_CLOSE_ALREADY_FLAT"}
            if not rows:
                exit_price=self.lab._execution_price(order,symbol); entry=_decimal(local["entry_price"]); qty=_decimal(local["quantity"])
                pnl=(exit_price-entry)*qty if local["direction"]=="LONG" else (entry-exit_price)*qty
                closed=self.ledger.close_forward_position(symbol=symbol,exit_price=float(exit_price),gross_pnl=float(pnl),exit_reason="RECOVERED_CLOSE")
                self.ledger.set_setting("forward_pending_order",None)
                return {"resolved":True,"status":"RECOVERED_CLOSE","trade":closed}
            self._assert_identity(symbol,local,rows)
            return {"resolved":False,"status":"FILLED_POSITION_STILL_VISIBLE","pending":pending}

        # A FILLED opening order with no remaining exposure is operationally
        # safe but cannot be represented as an open position. Quarantine the
        # accounting gap rather than trapping Futures forever.
        if local is None and not rows:
            self._mark_evidence_gap("FILLED_OPEN_NOW_FLAT",symbol,"Opening order was FILLED but current exchange exposure is zero")
            self.ledger.set_setting("forward_open_plan",None)
            self.ledger.set_setting("forward_pending_order",None)
            return {"resolved":True,"status":"QUARANTINED_FILLED_OPEN_NOW_FLAT"}

        return {"resolved":False,"status":"RECOVERY_STATE_CHANGED","pending":pending}

    def protection_tick(self)->dict:
        if not self.settings.forward_enabled: return {"enabled":False}
        pending=self._recover_journal()
        if pending and not pending.get("resolved"): return {"enabled":True,"status":"PENDING_RECONCILIATION"}
        # When an automatic pause is already flat, the protection loop can
        # safely complete recovery instead of waiting for the next 15-minute
        # strategy cycle. Manual pauses remain untouched.
        if self.killed() and not self.ledger.forward_positions():
            if self._attempt_auto_recovery():
                return {"enabled":True,"status":"RECOVERED","closed":[]}
            return {"enabled":True,"status":"KILLED","closed":[]}
        closed=[]
        for local in self.ledger.forward_positions():
            symbol=local["symbol"]
            try:
                raw_rows=self._actual_rows(symbol)
                self._assert_identity(symbol,local,raw_rows)
                if str(raw_rows[0].get("marginType","")).lower()!="isolated":
                    closed.append(self._repair_cross_position(local,raw_rows[0]))
                    continue
                rows=self._validated_rows(symbol, local)
            except Exception as exc:self._halt(str(exc)); raise
            mark=_decimal(rows[0].get("markPrice","0"))
            if mark<=0: raise FuturesTestnetExecutionError("Futures mark price unavailable")
            hit=(local["direction"]=="LONG" and (mark<=_decimal(local["stop_price"]) or mark>=_decimal(local["take_profit"]))) or (
                 local["direction"]=="SHORT" and (mark>=_decimal(local["stop_price"]) or mark<=_decimal(local["take_profit"])))
            if hit:
                reason="STOP" if ((local["direction"]=="LONG" and mark<=_decimal(local["stop_price"])) or (local["direction"]=="SHORT" and mark>=_decimal(local["stop_price"]))) else "TAKE_PROFIT"
                closed.append(self._close(local,reason))
            else:
                self.native.ensure(local)
        return {"enabled":True,"status":"CLOSED" if closed else ("OPEN" if self.ledger.forward_positions() else "FLAT"),"closed":closed}

    def cycle_symbol(self,symbol:str,candles:list[Candle],account:dict)->dict:
        self.native.reconcile(symbol)
        local=self.ledger.forward_position(symbol); rows=self._validated_rows(symbol, local)
        if local: self.native.ensure(local)
        if not candles:
            return {"symbol":symbol,"status":"NO_DATA"}
        if not self.ledger.claim_forward_decision(symbol, candles[-1].close_time):
            return {"symbol":symbol,"status":"NO_NEW_CANDLE"}
        signal={**self._signal(candles),"symbol":symbol,"timeframe":self.config.bot.timeframe,
                "candle_close_time":candles[-1].close_time}
        self.ledger.record_signal(symbol,signal)
        self.ledger.set_setting(f"forward_last_signal_{symbol}",{**signal,"at":datetime.now(UTC).isoformat()})
        self.ledger.shadow_step(symbol,signal,self._shadow_variants())
        if local:
            opposite=(local["direction"]=="LONG" and signal["short_score"]>=self.settings.forward_min_score) or (local["direction"]=="SHORT" and signal["long_score"]>=self.settings.forward_min_score)
            if opposite:return {"symbol":symbol,"status":"CLOSED","trade":self._close(local,"OPPOSITE_SIGNAL"),"signal":signal}
            return {"symbol":symbol,"status":"OPEN","position":local,"signal":signal}
        if signal["direction"] is None:return {"symbol":symbol,"status":"FLAT","signal":signal}
        if len(self.ledger.forward_positions())>=self.settings.forward_max_positions:return {"symbol":symbol,"status":"POSITION_LIMIT","signal":signal}
        if self.killed(): return {"symbol":symbol,"status":"KILLED","signal":signal}
        quantity=self.lab._validate_smoke_quantity(symbol,signal["direction"])
        estimated=_decimal(signal["price"])*quantity
        budget=Decimal(str(self.settings.forward_margin_usdt))
        if estimated>budget:
            return {"symbol":symbol,"status":"BUDGET_LIMIT","signal":signal}
        if _decimal(account["available_balance"])<max(budget,estimated)*Decimal("1.25"):
            return {"symbol":symbol,"status":"MARGIN_LIMIT","signal":signal}
        distance=max(self.settings.forward_stop_atr_multiple*signal["atr"],
                     self.settings.forward_minimum_stop_pct*signal["price"])
        trial_index = int(self.ledger.setting("forward_leverage_trial_cursor") or 0)
        leverage = self.settings.forward_leverage_trials[trial_index % len(self.settings.forward_leverage_trials)]
        if float(quantity) * distance >= float(estimated) / leverage * 0.8:
            return {"symbol": symbol, "status": "TRIAL_MARGIN_RISK_LIMIT", "signal": signal}
        signal={**signal,"proposed_quantity":float(quantity),"proposed_notional_usdt":float(estimated),
                "proposed_stop_distance":distance,"estimated_stop_loss_usdt":float(quantity)*distance,
                "proposed_leverage": leverage}
        if not self.ledger.claim_ai_budget(self.config.ai.max_reviews_per_day):
            return {"symbol":symbol,"status":"AI_BUDGET","signal":signal}
        ai_review=self.ai.review_futures(signal,{"wallet_balance":float(account["wallet_balance"]),"available_balance":float(account["available_balance"]),
            "unrealized_pnl":float(account["unrealized_pnl"]),"open_positions":float(len(self.ledger.forward_positions())),"automatic_leverage":float(leverage)})
        review={"model":self.config.ai.model,"verdict":ai_review.verdict,"confidence":ai_review.confidence,"reason":ai_review.reason,
                "direction":signal["direction"],"score":int(signal["score"]),"at":datetime.now(UTC).isoformat()}
        self.ledger.set_setting(f"forward_last_ai_review_{symbol}",review)
        if ai_review.verdict!="ALLOW" or ai_review.risk_multiplier<=0:return {"symbol":symbol,"status":"AI_REJECTED","signal":signal,"ai_review":review}
        if self.killed(): return {"symbol":symbol,"status":"KILLED","signal":signal}
        side="BUY" if signal["direction"]=="LONG" else "SELL"
        plan={"symbol":symbol,"direction":signal["direction"],"leverage":leverage,"leverage_trial_index":trial_index,
              "score":int(signal["score"]),"atr":float(signal["atr"]),"opened_at":datetime.now(UTC).isoformat()}
        self.lab.ensure_flat_forward_configuration(symbol, leverage)
        self.ledger.set_setting("forward_open_plan",plan)
        if self.killed():
            self.ledger.set_setting("forward_open_plan",None)
            return {"symbol":symbol,"status":"KILLED","signal":signal}
        order=self.lab.forward_submit(symbol=symbol,side=side,quantity=quantity,reduce_only=False)
        rows=self._actual_rows(symbol)
        if len(rows)!=1: raise FuturesTestnetExecutionError(f"Futures forward open position not found: {symbol}")
        row=self.lab.ensure_forward_position_configuration(symbol, rows[0], leverage)
        amount=_decimal(row["positionAmt"]); actual_qty=abs(amount); entry=_decimal(row.get("entryPrice",order.get("avgPrice","0")))
        if entry<=0: entry=self.lab._execution_price(order,symbol)
        distance=max(Decimal(str(self.settings.forward_stop_atr_multiple*signal["atr"])),Decimal(str(self.settings.forward_minimum_stop_pct))*entry)
        direction=signal["direction"]; stop=entry-distance if direction=="LONG" else entry+distance
        take=entry+Decimal(str(self.settings.forward_reward_to_risk))*distance if direction=="LONG" else entry-Decimal(str(self.settings.forward_reward_to_risk))*distance
        liquidation=_decimal(row.get("liquidationPrice","0"))
        position={"symbol":symbol,"direction":direction,"leverage":leverage,"leverage_trial_index":trial_index,
            "quantity":float(actual_qty),"entry_price":float(entry),"stop_price":float(stop),
            "take_profit":float(take),"liquidation_price":float(liquidation) if liquidation>0 else None,"signal_score":int(signal["score"]),"opened_at":plan["opened_at"]}
        self.ledger.set_forward_position(position); self.ledger.set_setting("forward_open_plan",None); self.ledger.set_setting("forward_pending_order",None)
        self.native.ensure(position)
        return {"symbol":symbol,"status":"OPENED","position":position,"signal":signal,"ai_review":review}

    def cycle(self,candle_map:dict[str,list[Candle]])->dict:
        if not self.settings.forward_enabled:return {"enabled":False,"status":"OFF"}
        if self.killed() and not self._attempt_auto_recovery():
            return {"enabled":True,"status":"KILLED"}
        pending=self._recover_journal()
        if pending and not pending.get("resolved"):return {"enabled":True,"status":"PENDING_RECONCILIATION"}
        self.protection_tick()
        health=self._preflight_flat_symbols()
        account=self._record_account(); results=[]
        if self._risk_halt(account):
            return {"enabled":True,"status":"RISK_HALT",**account}
        for symbol in self.symbols:
            if health.get(symbol,{}).get("status")=="BLOCKED" and self.ledger.forward_position(symbol) is None:
                results.append({"symbol":symbol,"status":"BLOCKED","error":health[symbol].get("error")})
                continue
            candles=candle_map.get(symbol)
            if not candles: results.append({"symbol":symbol,"status":"NO_DATA"}); continue
            results.append(self.cycle_symbol(symbol,candles,account))
        return {"enabled":True,"status":"ACTIVE","results":results,"symbol_health":health,**account}

    def _risk_halt(self, account: dict) -> bool:
        """Independent account loss gates; never inhibit protective closes."""
        now = datetime.now(UTC)
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week = day - timedelta(days=day.weekday())
        equity = float(account["wallet_balance"]) + float(account["unrealized_pnl"])
        for name, start, limit in (("daily", day, self.config.risk.daily_loss_limit_pct),
                                   ("weekly", week, self.config.risk.weekly_loss_limit_pct)):
            key = "forward_" + name + "_loss_halt"
            if self.ledger.setting(key) == start.isoformat():
                return True
            baseline = self.ledger.equity_baseline(start.isoformat())
            if baseline is not None and baseline > 0 and equity / baseline - 1 <= -limit:
                self.ledger.set_setting(key, start.isoformat())
                self.ledger.set_setting("forward_last_risk_halt", {"period":name,"at":now.isoformat(),
                    "return_pct":100 * (equity / baseline - 1)})
                return True
        return False

    def snapshot(self)->dict:
        data=self.ledger.forward_snapshot()
        return {"enabled":self.settings.forward_enabled,"killed":self.killed(),"symbols":list(self.symbols),
            "leverage_trials": self.ledger.leverage_trial_status(self.settings.forward_leverage_trials, self.settings.forward_margin_usdt),
            "automatic_leverage":1,"latest_signals":{s:self.ledger.setting(f"forward_last_signal_{s}") for s in self.symbols},
            "last_error":self.ledger.setting("forward_last_error"),"ai_model":self.config.ai.model,
            "last_ai_reviews":{s:self.ledger.setting(f"forward_last_ai_review_{s}") for s in self.symbols},
            "symbol_health":self.ledger.setting("forward_symbol_health") or {},
            "last_auto_recovery":self.ledger.setting("forward_last_auto_recovery"),
            "native_protection":projection(self.ledger.setting(FUTURES_KEY) or {}),
            "recovery":{"durable_order_journal":True,"startup_position_reconciliation":True,"separate_kill_switch":True,
                        "automatic_config_repair":True,"automatic_safe_resume":True,
                        "native_exchange_stop_orders":True},**data}
