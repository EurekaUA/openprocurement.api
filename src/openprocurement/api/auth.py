# -*- coding: utf-8 -*-
import os
import binascii
from hashlib import sha512

from pyramid.authentication import BasicAuthAuthenticationPolicy, b64decode
from ConfigParser import ConfigParser


auth_mapping = {}


def auth(auth_type=None):
    def decorator(func):
        auth_mapping[auth_type] = func
        return func
    return decorator


@auth(auth_type="file")
def _file_auth(app_meta):
    conf_auth = app_meta(('config', 'auth'))
    config = ConfigParser()
    file_path = os.path.join(app_meta(['here']), conf_auth.get('src', None))
    config.read(file_path)
    users = {}

    for item in config.sections():
        for key, value in config.items(item):
            single_value = {
                'name': key,
                'level': value.split(',', 1)[1] if ',' in value else '1234',
                'group': item
            }
            single_key = value.split(',', 1)[0]
            user = {single_key:single_value}
            users.update(user)
    return users


def _auth_factory(auth_type):
    auth_func = auth_mapping.get(auth_type, None)
    return auth_func


def get_auth(app_meta):
    auth_type = app_meta(('config', 'auth', 'type'), None)
    auth_func = _auth_factory(auth_type)
    return auth_func(app_meta)


class AuthenticationPolicy(BasicAuthAuthenticationPolicy):

    def __init__(self, users, realm='OpenProcurement', debug=False):
        self.realm = realm
        self.debug = debug
        self.users = users

    def unauthenticated_userid(self, request):
        """ The userid parsed from the ``Authorization`` request header."""
        token = self._get_credentials(request)
        if token:
            user = self.users.get(token)
            if user:
                return user['name']
            toket_sha512 = sha512(token).hexdigest()
            user = self.users.get(toket_sha512)
            if user:
                return user['name']

    def check(self, user, request):
        token = request.params.get('acc_token')
        auth_groups = ['g:{}'.format(user['group'])]
        for i in user['level']:
            auth_groups.append('a:{}'.format(i))
        if not token:
            token = request.headers.get('X-Access-Token')
            if not token:
                if request.method in ['POST', 'PUT', 'PATCH'] and request.content_type == 'application/json':
                    try:
                        json = request.json_body
                    except ValueError:
                        json = None
                    token = isinstance(json, dict) and json.get('access', {}).get('token')
                if not token:
                    return auth_groups
        auth_groups.append('{}_{}'.format(user['name'], token))
        auth_groups.append('{}_{}'.format(user['name'], sha512(token).hexdigest()))
        return auth_groups

    def callback(self, username, request):
        # Username arg is ignored.  Unfortunately _get_credentials winds up
        # getting called twice when authenticated_userid is called.  Avoiding
        # that, however, winds up duplicating logic from the superclass.
        token = self._get_credentials(request)
        if token:
            user = self.users.get(token)
            if user:
                return self.check(user, request)
            toket_sha512 = sha512(token).hexdigest()
            user = self.users.get(toket_sha512)
            if user:
                return self.check(user, request)

    def _get_credentials(self, request):
        authorization = request.headers.get('Authorization')
        if not authorization:
            return None
        try:
            authmeth, auth = authorization.split(' ', 1)
        except ValueError:  # not enough values to unpack
            return None
        if authmeth.lower() == 'bearer':
            return auth
        if authmeth.lower() != 'basic':
            return None

        try:
            authbytes = b64decode(auth.strip())
        except (TypeError, binascii.Error):  # can't decode
            return None

        # try utf-8 first, then latin-1; see discussion in
        # https://github.com/Pylons/pyramid/issues/898
        try:
            auth = authbytes.decode('utf-8')
        except UnicodeDecodeError:  # pragma: no cover
            auth = authbytes.decode('latin-1')

        try:
            username, _ = auth.split(':', 1)
        except ValueError:  # not enough values to unpack
            return None
        return username


def get_local_roles(context):
    from pyramid.location import lineage
    roles = {}
    for location in lineage(context):
        try:
            local_roles = location.__local_roles__
        except AttributeError:
            continue
        if local_roles and callable(local_roles):
            local_roles = local_roles()
        roles.update(local_roles)
    return roles


def authenticated_role(request):
    principals = request.effective_principals
    if hasattr(request, 'context'):
        roles = get_local_roles(request.context)
        local_roles = [roles[i] for i in reversed(principals) if i in roles]
        if local_roles:
            return local_roles[0]
    groups = [g for g in reversed(principals) if g.startswith('g:')]
    return groups[0][2:] if groups else 'anonymous'


def check_accreditation(request, level):
    return "a:{}".format(level) in request.effective_principals
