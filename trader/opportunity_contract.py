"""Closed immutable numerical observations; no execution/admission capability."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import math
import re

MAX_EVENT_BYTES=4096
ENGINES=('SPOT','FUTURES','AI_MARKET_PULSE','QUANT_ARBITRAGE')
ENVIRONMENTS=('SPOT_TESTNET','FUTURES_DEMO','PAPER','SHADOW')
VENUES=('SPOT_TESTNET','FUTURES_DEMO','SPOT_REFERENCE','FUTURES_REFERENCE','SPOT','FUTURES','PAPER')
CHECKS=frozenset(('NATIVE_QUANTITATIVE_CHECKS_PASSED','INDIVIDUAL_AI_REVIEW_ACCEPTED','INDIVIDUAL_AI_REVIEW_ALLOW','INDIVIDUAL_AI_REVIEW_REDUCE',
    'NATIVE_FORWARD_CONFIGURATION_PASSED','SHADOW_COST_RISK_GATES_PASSED','SHADOW_LIQUIDITY_GATES_PASSED'))
LEG_KEYS=frozenset(('symbol','venue','direction','quantity','reference_price','stop_price','take_profit','fee_rate','slippage_rate','gross_notional','margin'))
FLAGS={'controls_enabled':False,'can_veto':False,'execution_enabled':False,'reservations_enabled':False,'promotion_allowed':False}


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')


def decimal_text(value):
    """Preserve native Decimal/float representation, without adjusting the plan."""
    if value is None:return None
    if type(value) not in (Decimal,str,int,float) or type(value) is str and len(value)>64:
        raise ValueError('INVALID_DECIMAL')
    if type(value) is float and not math.isfinite(value):raise ValueError('INVALID_DECIMAL')
    try:
        with localcontext() as context:
            context.prec=80
            number=Decimal(str(value))
            if not number.is_finite() or abs(number)>Decimal('1e18') or number<0 or number.as_tuple().exponent < -30:
                raise ValueError('INVALID_DECIMAL')
            result=format(number,'f')
            if '.' in result:result=result.rstrip('0').rstrip('.')
            result='0' if number==0 else result
            if len(result)>64:raise ValueError('INVALID_DECIMAL')
            return result
    except InvalidOperation:raise ValueError('INVALID_DECIMAL') from None


def timestamp(value):
    if value is None:return None
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<253402300799:
        raise ValueError('INVALID_TIMESTAMP')
    return float(value)


def closed_dict(value,keys):
    if value is None:return {}
    if type(value) is not dict or len(value)>len(keys) or any(type(key) is not str for key in value):raise ValueError('INVALID_FIELDS')
    if set(value)-set(keys):raise ValueError('INVALID_FIELDS')
    return value


def _identity(engine,environment,origin_ref,at):
    if type(engine) is not str or type(environment) is not str or engine not in ENGINES or environment not in ENVIRONMENTS:raise ValueError('INVALID_SCOPE')
    if engine=='SPOT' and environment not in ('SPOT_TESTNET','PAPER') or engine=='FUTURES' and environment!='FUTURES_DEMO' or engine in ENGINES[2:] and environment!='SHADOW':
        raise ValueError('INVALID_ENGINE_ENVIRONMENT')
    if type(origin_ref) is not str or not 1<=len(origin_ref)<=160:raise ValueError('INVALID_ORIGIN')
    observed=timestamp(at)
    if observed is None:raise ValueError('MISSING_PRODUCER_TIME')
    return {'schema':1,'engine':engine,'environment':environment,'at':observed,
            'origin_digest':hashlib.sha256(canonical([engine,environment,origin_ref])).hexdigest(),
            'account_identity':'UNKNOWN'}


@dataclass(frozen=True)
class OpportunityEvent:
    encoded:bytes
    id:str
    def payload(self):return json.loads(self.encoded)


def _freeze(value):
    raw=canonical(value)
    if len(raw)>MAX_EVENT_BYTES:raise ValueError('EVENT_SIZE_LIMIT')
    return OpportunityEvent(raw,hashlib.sha256(raw).hexdigest())


def build_intent(*,engine,environment,origin_ref,strategy_version,at,legs,capital=None,limits=None,evidence=None):
    result=_identity(engine,environment,origin_ref,at)
    if type(strategy_version) is not str or not re.fullmatch(r'[A-Za-z0-9_.:/-]{1,80}',strategy_version):raise ValueError('INVALID_STRATEGY_VERSION')
    if type(legs) not in (tuple,list) or not 1<=len(legs)<=4:raise ValueError('INVALID_LEGS')
    normalized=[]
    for item in legs:
        leg=closed_dict(item,LEG_KEYS)
        if (type(leg.get('symbol')) is not str or not re.fullmatch(r'[A-Z0-9]{2,24}USDT',leg['symbol'])
                or type(leg.get('venue')) is not str or type(leg.get('direction')) is not str
                or leg.get('venue') not in VENUES or leg.get('direction') not in ('LONG','SHORT')):raise ValueError('INVALID_LEG_IDENTITY')
        row={key:leg[key] for key in ('symbol','venue','direction')}
        row.update({key:decimal_text(leg.get(key)) for key in LEG_KEYS-{'symbol','venue','direction'}})
        normalized.append(row)
    cap=closed_dict(capital,('cash','equity','available','at'))
    cap={key:timestamp(cap.get(key)) if key=='at' else decimal_text(cap.get(key)) for key in ('cash','equity','available','at')}
    bounds=closed_dict(limits,('gross_limit','capital_limit','stop_risk_limit','max_positions'))
    bound_values={key:decimal_text(bounds.get(key)) for key in ('gross_limit','capital_limit','stop_risk_limit')}
    count=bounds.get('max_positions')
    if count is not None and (type(count) is not int or not 0<=count<=100):raise ValueError('INVALID_POSITION_LIMIT')
    bound_values['max_positions']=count
    source=closed_dict(evidence,('market_at','received_at','known_at','decision_at','source_digest','review_digest','policy_digest','checks'))
    metadata={key:timestamp(source.get(key)) for key in ('market_at','received_at','known_at','decision_at')}
    for key in ('source_digest','review_digest','policy_digest'):
        value=source.get(key)
        if value is not None and (type(value) is not str or not re.fullmatch(r'[a-f0-9]{64}',value)):raise ValueError('INVALID_EVIDENCE_DIGEST')
        metadata[key]=value
    checks=source.get('checks',())
    if type(checks) not in (tuple,list) or len(checks)>12 or any(type(code) is not str or code not in CHECKS for code in checks):raise ValueError('INVALID_CHECKS')
    metadata['checks']=list(dict.fromkeys(checks))
    result.update(kind='ENTRY_INTENT',strategy_version=strategy_version,legs=normalized,capital=cap,limits=bound_values,evidence=metadata)
    return _freeze(result)


def position_digest(engine, environment, position_ref):
    """Hash a durable position identity, never a symbol-only correlation."""
    if type(position_ref) is not str or not 1 <= len(position_ref) <= 160:
        raise ValueError('INVALID_POSITION_REFERENCE')
    return hashlib.sha256(canonical(['POSITION', engine, environment, position_ref])).hexdigest()


def build_outcome(*,engine,environment,origin_ref,at,stage,state,complete=False,evidence=None,by_position=False):
    result=_identity(engine,environment,origin_ref,at)
    if type(stage) is not str or type(state) is not str or stage not in ('EXCHANGE_RESPONSE','LEDGER_COMMIT') or state not in ('FILLED','PARTIAL','REJECTED','CANCELLED','UNKNOWN','OPENED','CLOSED') or type(complete) is not bool:
        raise ValueError('INVALID_OUTCOME')
    source=closed_dict(evidence,('response_digest','decision_digest','position_digest','quantity','remaining_quantity','fees'))
    metadata={key:decimal_text(source.get(key)) for key in ('quantity','fees')}
    for key in ('response_digest','decision_digest','position_digest'):
        value=source.get(key)
        if value is not None and (type(value) is not str or not re.fullmatch(r'[a-f0-9]{64}',value)):raise ValueError('INVALID_OUTCOME_DIGEST')
        if key=='position_digest':
            if value is not None:result[key]=value
        else:metadata[key]=value
    remaining=decimal_text(source.get('remaining_quantity'))
    if remaining is not None:result['remaining_quantity']=remaining
    if type(by_position) is not bool:
        raise ValueError('INVALID_POSITION_REFERENCE')
    if by_position:
        if (stage != 'LEDGER_COMMIT' or state not in ('CLOSED','PARTIAL')
                or result.get('position_digest') is None or metadata['decision_digest'] is None
                or remaining is None
                or complete != (state == 'CLOSED')
                or (remaining == '0') != (state == 'CLOSED')):
            raise ValueError('INVALID_POSITION_OUTCOME')
        result['position_reference']=True
    result.update(kind='ENTRY_OUTCOME',stage=stage,state=state,complete=complete,evidence=metadata)
    return _freeze(result)
