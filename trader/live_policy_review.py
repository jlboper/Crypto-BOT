"""Inactive numerical review templates; no policy capability or activation.

An owner's reviewed draft is metadata, never a machine authorization token.
This module has no credentials, exchange client, runtime configuration, protected
store, wallet constructor or ActivePolicy. It never constructs AdmissionPolicy.
Unknown costs, assets and operational thresholds remain explicitly unknown.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile


MAX_BYTES=32768
MAX_UNITS=9_000_000_000_000_000
_SCOPES=('SPOT_LIVE','FUTURES_LIVE')
_FALSE=('active','execution_enabled','capital_allocated','financial_authorization',
        'apply_to_current_testnet','automatic_activation','ready_for_live','materializable')
_REVIEW_FALSE=('execution_enabled','capital_allocated','financial_authorization','apply_to_current_testnet')
_ALLOWED={'schema','created_at','state',*_REVIEW_FALSE,'owner_approval_received','currency',
    'capital_budget','usd_budget_reference','usd_usdt_conversion_performed','wallet_budgets',
    'per_trade_estimated_stop_risk_cap','per_trade_risk_pct_of_each_wallet',
    'global_estimated_open_stop_risk_cap','daily_loss_cap_utc','weekly_loss_cap_utc',
    'cashflow_adjusted_drawdown_cap','wallet_loss_caps','max_positions_per_engine','max_positions_total',
    'spot_leverage','futures_max_leverage','futures_margin_mode_required','futures_position_mode_required',
    'gross_exposure_caps','risk_aggregation','initial_engines','pulse_quant','testnet_current_ceiling_reference',
    'hypothesis_only','statistically_optimal_claim','stop_risk_includes','limitations',
    'owner_reviewed_at','owner_approval_source'}
_POLICY_FIELDS=('policy_id','approval_reference','approved_at','capital_budget_units','gross_limit_units',
    'stop_risk_limit_units','per_trade_stop_risk_limit_units','max_positions','max_leverage_milli',
    'engine_limits','asset_limits','correlation_limits','daily_loss_limit_units','weekly_loss_limit_units',
    'drawdown_limit_units','caution_fraction_ppm','reduced_fraction_ppm','reduced_candidate_risk_cap_units',
    'max_data_age_seconds','max_reservation_age_seconds','max_fee_bps','max_slippage_bps','max_spread_bps')


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)


def _digest(value):return hashlib.sha256(canonical(value).encode('ascii')).hexdigest()


def _at(value):
    if type(value) is not str or len(value)>40:
        raise ValueError('EXPLICIT_REVIEW_UTC_REQUIRED')
    at=datetime.fromisoformat(value.replace('Z','+00:00'))
    if at.tzinfo is None or at.utcoffset().total_seconds()!=0:
        raise ValueError('EXPLICIT_REVIEW_UTC_REQUIRED')
    return at.astimezone(UTC)


def _utc():return datetime.now(UTC).isoformat(timespec='microseconds').replace('+00:00','Z')


def _text(value,*,maximum=256):
    if type(value) is not str or not 1<=len(value)<=maximum or any(ord(c)<32 for c in value):
        raise ValueError('BOUNDED_REVIEW_TEXT_REQUIRED')
    return value


def _number(value,*,maximum=MAX_UNITS):
    if type(value) not in (int,float):raise ValueError('EXPLICIT_FINITE_REVIEW_NUMBER_REQUIRED')
    try:result=Decimal(str(value))
    except InvalidOperation:raise ValueError('EXPLICIT_FINITE_REVIEW_NUMBER_REQUIRED') from None
    if not result.is_finite() or not 0<result<=maximum:
        raise ValueError('POSITIVE_BOUNDED_REVIEW_NUMBER_REQUIRED')
    return result


def _money(value):
    units=_number(value)*1_000_000
    if units!=units.to_integral_value() or units>MAX_UNITS:
        raise ValueError('EXACT_MICRO_USDT_REVIEW_REQUIRED')
    return int(units)


def _integer(value,maximum):
    if type(value) is not int or not 1<=value<=maximum:
        raise ValueError('EXPLICIT_BOUNDED_REVIEW_INTEGER_REQUIRED')
    return value


def _optional(mapping,key,parser):
    return parser(mapping[key]) if key in mapping else None


def _closed(value,keys):
    if type(value) is not dict or not set(value)<=set(keys):raise ValueError('CLOSED_REVIEW_OBJECT_REQUIRED')
    return value


def _envelope(total,components):
    """Known amounts give a lower bound; unknown amounts remain unresolved."""
    if total is not None and sum(term for term in components if term is not None)>total:
        raise ValueError('REVIEW_COMPONENTS_EXCEED_ENVELOPE')


def _ceiling(value,ceiling):
    if value is not None and ceiling is not None and value>ceiling:
        raise ValueError('REVIEW_COMPONENT_EXCEEDS_LIMIT')


def prepare_live_policy_review(value,*,created_at):
    """Pure review projection from explicit JSON; missing limits remain None.

    Output may resemble AdmissionPolicy fields for human comparison, but its
    identities/approval fields and undefined thresholds are null. Even a fully
    specified numerical draft remains inactive and cannot be materialized here.
    """
    _closed(value,_ALLOWED)
    if len(canonical(value))>MAX_BYTES or value.get('schema')!='policy-review-proposal/v1':
        raise ValueError('BOUNDED_REVIEW_PROPOSAL_REQUIRED')
    value=json.loads(canonical(value))  # Detach retained metadata from caller mutation.
    if value.get('state') not in {'OWNER_REVIEWED_INACTIVE','DRAFT_INACTIVE'} or any(
            value.get(key) is not False for key in _REVIEW_FALSE):
        raise ValueError('EXPLICIT_INACTIVE_REVIEW_REQUIRED')
    at=_at(created_at)
    for key in ('created_at','owner_reviewed_at'):
        if key in value and _at(value[key])>at:raise ValueError('FUTURE_OWNER_REVIEW_UNAVAILABLE')
    for key in ('owner_approval_received','usd_usdt_conversion_performed','hypothesis_only','statistically_optimal_claim'):
        if key in value and type(value[key]) is not bool:raise ValueError('EXPLICIT_REVIEW_BOOLEAN_REQUIRED')
    if value.get('usd_usdt_conversion_performed') is True or value.get('statistically_optimal_claim') is True:
        raise ValueError('REVIEW_MUST_NOT_ASSERT_CONVERSION_OR_OPTIMALITY')
    if 'currency' in value and value['currency']!='USDT':raise ValueError('EXPLICIT_USDT_REVIEW_REQUIRED')
    if 'currency' not in value and any(key in value for key in ('capital_budget','wallet_budgets',
            'wallet_loss_caps','gross_exposure_caps','per_trade_estimated_stop_risk_cap',
            'global_estimated_open_stop_risk_cap','daily_loss_cap_utc','weekly_loss_cap_utc','cashflow_adjusted_drawdown_cap')):
        raise ValueError('CURRENCY_REQUIRED_FOR_EXPLICIT_MONETARY_LIMITS')
    if value.get('owner_approval_received') is True and value['state']!='OWNER_REVIEWED_INACTIVE':
        raise ValueError('CONSISTENT_OWNER_REVIEW_METADATA_REQUIRED')
    if 'initial_engines' in value:
        rows=value['initial_engines']
        if (type(rows) is not list or not rows or len(rows)!=len(set(rows))
                or any(row not in {'SPOT','FUTURES'} for row in rows)):
            raise ValueError('EXPLICIT_INITIAL_REVIEW_ENGINES_REQUIRED')
    for key,allowed in (('risk_aggregation','GROSS_NO_SHORT_HEDGE_CREDIT'),
            ('pulse_quant','SHADOW_ONLY_UNTIL_SEPARATE_PROMOTION'),('futures_margin_mode_required','ISOLATED'),
            ('futures_position_mode_required','ONE_WAY')):
        if key in value and value[key]!=allowed:raise ValueError('REVIEW_SAFETY_CONSTRAINT_CHANGED')
    for key in ('stop_risk_includes','limitations'):
        if key in value:
            if type(value[key]) is not list or len(value[key])>32:raise ValueError('BOUNDED_REVIEW_NOTES_REQUIRED')
            for row in value[key]:_text(row)
    if 'testnet_current_ceiling_reference' in value:
        reference=_closed(value['testnet_current_ceiling_reference'],
            {'per_trade_pct','daily_loss_pct','weekly_loss_pct','futures_current_forward_leverage'})
        for item in reference.values():_number(item,maximum=100)
        # Retain only its digest. It is contextual evidence, never a request to
        # increase, copy or apply limits to the current Testnet configurations.
    budget=_optional(value,'capital_budget',_money)
    risk=_optional(value,'global_estimated_open_stop_risk_cap',_money)
    trade=_optional(value,'per_trade_estimated_stop_risk_cap',_money)
    daily=_optional(value,'daily_loss_cap_utc',_money)
    weekly=_optional(value,'weekly_loss_cap_utc',_money)
    drawdown=_optional(value,'cashflow_adjusted_drawdown_cap',_money)
    for component in (risk,trade,daily,weekly,drawdown):_ceiling(component,budget)
    _ceiling(trade,risk)
    percentage=_optional(value,'per_trade_risk_pct_of_each_wallet',lambda v:_number(v,maximum=100))
    wallets=_closed(value.get('wallet_budgets',{}),_SCOPES)
    caps=_closed(value.get('wallet_loss_caps',{}),_SCOPES)
    gross=_closed(value.get('gross_exposure_caps',{}),{*_SCOPES,'total_static_envelope','per_asset'})
    wallet_units={scope:_optional(wallets,scope,_money) for scope in _SCOPES}
    gross_units={key:_optional(gross,key,_money) for key in (*_SCOPES,'total_static_envelope','per_asset')}
    limits={}
    for scope in _SCOPES:
        row=_closed(caps.get(scope,{}),{'daily','weekly','drawdown','open_stop_risk'})
        limits[scope]={key:_optional(row,key,_money) for key in ('daily','weekly','drawdown','open_stop_risk')}
        for amount in limits[scope].values():_ceiling(amount,wallet_units[scope])
        _ceiling(trade,limits[scope]['open_stop_risk'])
        if trade is not None and wallet_units[scope] is not None and percentage is not None:
            if Decimal(trade)>Decimal(wallet_units[scope])*percentage/100:
                raise ValueError('PER_TRADE_CAP_EXCEEDS_REVIEWED_WALLET_PERCENTAGE')
    _envelope(budget,list(wallet_units.values()))
    for total,key in ((risk,'open_stop_risk'),(daily,'daily'),(weekly,'weekly'),(drawdown,'drawdown')):
        _envelope(total,[limits[scope][key] for scope in _SCOPES])
    _envelope(gross_units['total_static_envelope'],[gross_units[scope] for scope in _SCOPES])
    _ceiling(gross_units['per_asset'],gross_units['total_static_envelope'])
    positions=_optional(value,'max_positions_per_engine',lambda v:_integer(v,100))
    total_positions=_optional(value,'max_positions_total',lambda v:_integer(v,100))
    if 'initial_engines' in value and positions is not None:_ceiling(positions*len(value['initial_engines']),total_positions)
    spot=_optional(value,'spot_leverage',lambda v:_integer(v,1))
    futures=_optional(value,'futures_max_leverage',lambda v:_integer(v,125))
    for scope,leverage in zip(_SCOPES,(spot,futures)):
        _ceiling(gross_units[scope],None if wallet_units[scope] is None or leverage is None else wallet_units[scope]*leverage)
    templates={}
    for scope,engine,leverage in zip(_SCOPES,('SPOT','FUTURES'),(spot,futures)):
        policy=dict.fromkeys(_POLICY_FIELDS)
        policy.update(capital_budget_units=wallet_units[scope],gross_limit_units=gross_units[scope],
            stop_risk_limit_units=limits[scope]['open_stop_risk'],per_trade_stop_risk_limit_units=trade,
            max_positions=positions,max_leverage_milli=None if leverage is None else leverage*1000,
            daily_loss_limit_units=limits[scope]['daily'],weekly_loss_limit_units=limits[scope]['weekly'],
            drawdown_limit_units=limits[scope]['drawdown'])
        if all(policy[k] is not None for k in ('capital_budget_units','gross_limit_units','stop_risk_limit_units')):
            policy['engine_limits']=[[engine,policy['capital_budget_units'],policy['gross_limit_units'],policy['stop_risk_limit_units']]]
        templates[scope]={'state':'INCOMPLETE_INACTIVE_TEMPLATE','materializable':False,
            'environment':scope,'engine':engine,'account_reference':None,'admission_policy_fields':policy,
            'unknown_fields':sorted(k for k,v in policy.items() if v is None)}
    metadata={'recorded_received':value.get('owner_approval_received'),
        'recorded_at':value.get('owner_reviewed_at'),
        'recorded_source':_optional(value,'owner_approval_source',_text),'grants_financial_authority':False}
    return {'schema':'inactive-live-policy-template/v1','state':'INACTIVE_REVIEW_ONLY',
        'created_at':at.isoformat(timespec='microseconds').replace('+00:00','Z'),
        **{key:False for key in _FALSE},'hypothesis_only':True,'statistically_optimal_claim':False,
        'source_review_digest':_digest(value),'owner_review_metadata':metadata,
        'currency':value.get('currency'),'quote_unit_scale':6,'usd_usdt_conversion_performed':False,
        'usd_budget_reference':_optional(value,'usd_budget_reference',lambda v:float(_number(v))),
        'global_nominal_limits':{'capital_budget_units':budget,'stop_risk_limit_units':risk,
            'per_trade_stop_risk_limit_units':trade,'daily_loss_limit_units':daily,'weekly_loss_limit_units':weekly,
            'drawdown_limit_units':drawdown,'max_positions':total_positions,
            'gross_limit_units':gross_units['total_static_envelope'],'per_asset_gross_limit_units':gross_units['per_asset']},
        'wallet_templates':templates,
        'explicit_constraints':{key:value.get(key) for key in ('risk_aggregation','initial_engines',
            'pulse_quant','futures_margin_mode_required','futures_position_mode_required','stop_risk_includes',
            'per_trade_risk_pct_of_each_wallet')},
        'unresolved_requirements':['ACCOUNT_BINDING','ASSET_UNIVERSE_AND_ASSET_STOP_RISK_LIMITS',
            'CORRELATION_GROUP_LIMITS','COST_SPREAD_SLIPPAGE_THRESHOLDS','CAUTION_AND_REDUCED_RISK_THRESHOLDS',
            'DATA_AND_RESERVATION_FRESHNESS_THRESHOLDS','FINANCIAL_FORWARD_EVIDENCE','FINAL_OWNER_ACTIVATION'],
        'testnet_reference_digest':_digest(value['testnet_current_ceiling_reference']) if 'testnet_current_ceiling_reference' in value else None,
        'limitations':value.get('limitations')}


def _regular(path,*,existing):
    path=Path(path).absolute()
    if (len(str(path))>4096 or path.drive.startswith('\\\\')
            or any(p.is_symlink() or getattr(p,'is_junction',lambda:False)() for p in (path,*path.parents))
            or not path.parent.is_dir()):raise ValueError('REGULAR_LOCAL_REVIEW_PATH_REQUIRED')
    if os.name=='nt' and any(':' in part or Path(part).is_reserved() for part in path.parts[1:]):
        raise ValueError('REGULAR_LOCAL_REVIEW_PATH_REQUIRED')
    if path.exists():
        info=path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:raise ValueError('REGULAR_SINGLE_LINK_REVIEW_REQUIRED')
    elif existing:raise ValueError('EXPLICIT_REVIEW_FILE_REQUIRED')
    return path


def load_policy_review(path):
    path=_regular(path,existing=True)
    def unique(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('DUPLICATE_REVIEW_KEY')
            result[key]=value
        return result
    before=path.stat()
    with path.open('rb') as stream:
        opened=os.fstat(stream.fileno())
        if (not stat.S_ISREG(opened.st_mode) or opened.st_nlink!=1 or opened.st_size>MAX_BYTES
                or (opened.st_dev,opened.st_ino)!=(before.st_dev,before.st_ino)):
            raise ValueError('BOUNDED_REGULAR_REVIEW_REQUIRED')
        raw=stream.read(MAX_BYTES+1);after=os.fstat(stream.fileno())
    if len(raw)>MAX_BYTES or (opened.st_size,opened.st_mtime_ns)!=(after.st_size,after.st_mtime_ns):
        raise ValueError('REVIEW_CHANGED_OR_TOO_LARGE')
    return json.loads(raw.decode('utf-8'),object_pairs_hook=unique,
        parse_constant=lambda _:(_ for _ in ()).throw(ValueError('NONFINITE_REVIEW_NUMBER')))


def _write_new(path,value):
    fd,temporary=tempfile.mkstemp(prefix='.inactive-policy-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(canonical(value).encode('ascii'));stream.flush();os.fsync(stream.fileno())
        if os.name=='nt':
            import ctypes
            from ctypes import wintypes
            move=ctypes.WinDLL('kernel32',use_last_error=True).MoveFileExW
            move.argtypes=(wintypes.LPCWSTR,wintypes.LPCWSTR,wintypes.DWORD);move.restype=wintypes.BOOL
            if not move(temporary,str(path),0x8):raise OSError('NEW_INACTIVE_REVIEW_OUTPUT_REQUIRED')
        else:
            os.link(temporary,path)  # Atomic exclusive publication; never overwrite.
            os.unlink(temporary)
            directory=os.open(path.parent,os.O_RDONLY|getattr(os,'O_DIRECTORY',0))
            try:os.fsync(directory)
            finally:os.close(directory)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def prepare_live_policy_file(review_path,output_path,*,clock=_utc):
    """Create one NEW review JSON artifact. No active or protected-store output."""
    source=_regular(review_path,existing=True);output=_regular(output_path,existing=False)
    if output.exists() or output==source or output.suffix.lower()!='.json':
        raise ValueError('NEW_SEPARATE_JSON_REVIEW_OUTPUT_REQUIRED')
    value=prepare_live_policy_review(load_policy_review(source),created_at=clock())
    _write_new(output,value)
    return {'state':'INACTIVE_REVIEW_FILE_CREATED','schema':value['schema'],
        'source_review_digest':value['source_review_digest'],**{key:False for key in _FALSE}}
