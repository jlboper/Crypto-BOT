"""Dedicated LIVE credential vault. Possession never authorizes orders."""
from .live_transport import LiveCredentials, LiveError
from .local_protection import ProtectedStore, UserProtection, ProtectionError, PURPOSES


class LiveCredentialVault:
    def __init__(self, path, *, protection=None):
        self.store = ProtectedStore(path, PURPOSES[0], protection=protection)

    def read(self):
        try:
            value = self.store.read()
        except ProtectionError:
            raise LiveError('USER_PROTECTED_RECORD_UNAVAILABLE') from None
        if (type(value) is not dict or set(value) != {'schema', 'orders_enabled', 'credentials'}
                or type(value['schema']) is not int or value['schema'] != 1 or value['orders_enabled'] is not False
                or type(value['credentials']) is not dict or not value['credentials']
                or set(value['credentials']) - {'SPOT_LIVE', 'FUTURES_LIVE'}):
            raise LiveError('INVALID_LIVE_CREDENTIAL_VAULT')
        result = {}
        for scope, pair in value['credentials'].items():
            if type(pair) is not dict or set(pair) != {'api_key', 'api_secret'}:
                raise LiveError('INVALID_LIVE_CREDENTIAL_VAULT')
            result[scope] = LiveCredentials(pair['api_key'], pair['api_secret'])
        return result

    def configure(self, credentials, *, replace=False):
        if (type(credentials) is not dict or not credentials
                or set(credentials) - {'SPOT_LIVE', 'FUTURES_LIVE'}
                or any(type(pair) is not LiveCredentials for pair in credentials.values())):
            raise LiveError('EXPLICIT_LIVE_CREDENTIALS_REQUIRED')
        try:
            self.store.write({'schema': 1, 'orders_enabled': False,
            'credentials': {scope: {'api_key': pair.api_key, 'api_secret': pair.api_secret}
                            for scope, pair in credentials.items()}}, replace=replace)
        except (ProtectionError, OSError):
            raise LiveError('USER_PROTECTED_RECORD_UNAVAILABLE') from None

    def status(self):
        try:
            scopes = sorted(self.read())
            return {'state': 'CONFIGURED_READ_ONLY', 'scopes': scopes, 'orders_enabled': False}
        except LiveError:
            return {'state': 'NOT_CONFIGURED_OR_UNAVAILABLE', 'scopes': [], 'orders_enabled': False}
