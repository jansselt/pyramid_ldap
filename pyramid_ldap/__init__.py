try:
    import ldap3
    from ldap3 import Server, Connection
    from ldap3 import AUTH_SIMPLE, STRATEGY_SYNC, STRATEGY_ASYNC_THREADED, SEARCH_SCOPE_WHOLE_SUBTREE, GET_ALL_INFO, \
        ALL_ATTRIBUTES, SEARCH_DEREFERENCE_ALWAYS
    from ldap3.abstraction import ObjectDef, AttrDef
except ImportError:  # pragma: no cover
    # this is for benefit of being able to build the docs on rtd.org
    class ldap(object):
        LDAPException = Exception
        SEARCH_SCOPE_SINGLE_LEVEL = None
        SEARCH_SCOPE_WHOLE_SUBTREE = None

import logging
import pprint
import time

from pyramid.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


class _LDAPQuery(object):
    """ Represents an LDAP query.  Provides rudimentary in-RAM caching of
    query results."""

    def __init__(self, base_dn, filter_tmpl, scope, cache_period):
        self.base_dn = base_dn
        self.filter_tmpl = filter_tmpl
        self.scope = scope
        self.cache_period = cache_period
        self.last_timeslice = 0
        self.cache = {}

    def __str__(self):
        return ('base_dn=%(base_dn)s, filter_tmpl=%(filter_tmpl)s, '
                'scope=%(scope)s, cache_period=%(cache_period)s' %
                self.__dict__)

    def query_cache(self, cache_key):
        result = None
        now = time.time()
        ts = _timeslice(self.cache_period, now)

        if ts > self.last_timeslice:
            logger.debug('dumping cache; now ts: %r, last_ts: %r' % (
                ts,
                self.last_timeslice)
            )
            self.cache = {}
            self.last_timeslice = ts

        result = self.cache.get(cache_key)

        return result

    def execute(self, conn, **kw):
        cache_key = (
            self.base_dn % kw,
            self.filter_tmpl % kw,
            self.scope,
            SEARCH_DEREFERENCE_ALWAYS,
            kw['attributes']
        )

        logger.debug('searching for %r' % (cache_key,))

        if self.cache_period:
            result = self.query_cache(cache_key)
            if result is not None:
                logger.debug('result for %r retrieved from cache' %
                             (cache_key,)
                )
            else:
                search_result = conn.search(*cache_key)
                if search_result:
                    result = conn.response
                    self.cache[cache_key] = result
                else:
                    result = {}
        else:
            search_result = conn.search(*cache_key)
            if search_result:
                result = conn.response
            else:
                result = {}

        logger.debug('search result: %r' % (result,))

        return result


def _timeslice(period, when=None):
    if when is None:  # pragma: no cover
        when = time.time()
    return when - (when % period)


class Connector(object):
    """ Provides API methods for accessing LDAP authentication information."""
    # def __init__(self, registry, manager):
    def __init__(self, registry, connection):
        self.registry = registry
        self.connection = connection

    def authenticate(self, login, password, attributes=ALL_ATTRIBUTES):
        """ Given a login name and a password, return a tuple of ``(dn,
        attrdict)`` if the matching user if the user exists and his password
        is correct.  Otherwise return ``None``.

        In a ``(dn, attrdict)`` return value, ``dn`` will be the
        distinguished name of the authenticated user.  Attrdict will be a
        dictionary mapping LDAP user attributes to sequences of values.  The
        keys and values in the dictionary values provided will be decoded
        from UTF-8, recursively, where possible.  The dictionary returned is
        a case-insensitive dictionary implemenation.

        A zero length password will always be considered invalid since it
        results in a request for "unauthenticated authentication" which should
        not be used for LDAP based authentication. See `section 5.1.2 of
        RFC-4513 <http://tools.ietf.org/html/rfc4513#section-5.1.2>`_ for a
        description of this behavior.

        If :meth:`pyramid.config.Configurator.ldap_set_login_query` was not
        called, using this function will raise an
        :exc:`pyramid.exceptions.ConfiguratorError`."""
        if password == '':
            return None

        #with self.manager.connection() as conn:
        #with self.connection as conn:
        conn = self.connection
        conn.open()
        search = getattr(self.registry, 'ldap_login_query', None)
        if search is None:
            raise ConfigurationError(
                'ldap_set_login_query was not called during setup')

        result = search.execute(conn, login=login, password=password, attributes=attributes)
        if len(result) > 1:
            conn.result['description'] = 'invalidCredentials'
            conn.result['message'] = ''
            return None
        elif len(result) < 1:
            conn.result['description'] = 'invalidCredentials'
            conn.result['message'] = ''
            return None
        else:
            login_dn = result[0]['dn']
        try:
            conn.user = login_dn
            conn.password = password
            conn.bind()
            # must invoke the __enter__ of this thing for it to connect
            return _ldap_decode(result[0])
        except ldap3.LDAPException:
            logger.debug('Exception in authenticate with login %r' % login,
                         exc_info=True)
            return None

    def user_groups(self, userdn, attributes=ALL_ATTRIBUTES):
        """ Given a user DN, return a sequence of LDAP attribute dictionaries
        matching the groups of which the DN is a member.  If the DN does not
        exist, return ``None``.

        In a return value ``[(dn, attrdict), ...]``, ``dn`` will be the
        distinguished name of the group.  Attrdict will be a dictionary
        mapping LDAP group attributes to sequences of values.  The keys and
        values in the dictionary values provided will be decoded from UTF-8,
        recursively, where possible.  The dictionary returned is a
        case-insensitive dictionary implemenation.
        
        If :meth:`pyramid.config.Configurator.ldap_set_groups_query` was not
        called, using this function will raise an
        :exc:`pyramid.exceptions.ConfiguratorError`
        """
        #with self.connection as conn:
        #with self.connection as conn:
        conn = self.connection
        search = getattr(self.registry, 'ldap_groups_query', None)
        if search is None:
            raise ConfigurationError(
                'set_ldap_groups_query was not called during setup')
        try:
            result = search.execute(conn, userdn=userdn, attributes=attributes)
            return _ldap_decode(result)
        except ldap3.LDAPException:
            logger.debug(
                'Exception in user_groups with userdn %r' % userdn,
                exc_info=True)
            return None


def ldap_set_login_query(config, base_dn, filter_tmpl,
                         scope=ldap3.SEARCH_SCOPE_SINGLE_LEVEL, cache_period=0):
    """ Configurator method to set the LDAP login search.  ``base_dn`` is the
    DN at which to begin the search.  ``filter_tmpl`` is a string which can
    be used as an LDAP filter: it should contain the replacement value
    ``%(login)s``.  Scope is any valid LDAP scope value
    (e.g. ``ldap.SEARCH_SCOPE_SINGLE_LEVEL``).  ``cache_period`` is the number of seconds
    to cache login search results; if it is 0, login search results will not
    be cached.

    Example::

        config.set_ldap_login_query(
            base_dn='CN=Users,DC=example,DC=com',
            filter_tmpl='(sAMAccountName=%(login)s)',
            scope=ldap.SEARCH_SCOPE_SINGLE_LEVEL,
            )

    The registered search must return one and only one value to be considered
    a valid login.
    """
    query = _LDAPQuery(base_dn, filter_tmpl, scope, cache_period)

    def register():
        config.registry.ldap_login_query = query

    intr = config.introspectable(
        'pyramid_ldap login query',
        None,
        str(query),
        'pyramid_ldap login query'
    )

    config.action('ldap-set-login-query', register, introspectables=(intr,))


def ldap_set_groups_query(config, base_dn, filter_tmpl,
                          scope=ldap3.SEARCH_SCOPE_WHOLE_SUBTREE, cache_period=0):
    """ Configurator method to set the LDAP groups search.  ``base_dn`` is
    the DN at which to begin the search.  ``filter_tmpl`` is a string which
    can be used as an LDAP filter: it should contain the replacement value
    ``%(userdn)s``.  Scope is any valid LDAP scope value
    (e.g. ``ldap.SEARCH_SCOPE_WHOLE_SUBTREE``).  ``cache_period`` is the number of seconds
    to cache groups search results; if it is 0, groups search results will
    not be cached.

    Example::

        config.set_ldap_groups_query(
            base_dn='CN=Users,DC=example,DC=com',
            filter_tmpl='(&(objectCategory=group)(member=%(userdn)s))'
            scope=ldap.SEARCH_SCOPE_WHOLE_SUBTREE,
            )

    """
    query = _LDAPQuery(base_dn, filter_tmpl, scope, cache_period)

    def register():
        config.registry.ldap_groups_query = query

    intr = config.introspectable(
        'pyramid_ldap groups query',
        None,
        str(query),
        'pyramid_ldap groups query'
    )
    config.action('ldap-set-groups-query', register, introspectables=(intr,))


def ldap_setup(config, host, port=389, useSsl=False, allowedReferralHosts=None, getInfo=None,
               tls=None, authentication=None):
    """ Configurator method to set up an LDAP connection pool.

    - **uri**: ldap server uri **[mandatory]**
    - **bind**: default bind that will be used to bind a connector.
      **default: None**
    - **passwd**: default password that will be used to bind a connector.
      **default: None**
    - **size**: pool size. **default: 10**
    - **retry_max**: number of attempts when a server is down. **default: 3**
    - **retry_delay**: delay in seconds before a retry. **default: .1**
    - **use_tls**: activate TLS when connecting. **default: False**
    - **timeout**: connector timeout. **default: -1**
    - **use_pool**: activates the pool. If False, will recreate a connector
       each time. **default: True**
    """
    vals = dict(
        host=host, port=port, useSsl=useSsl, allowedReferralHosts=allowedReferralHosts, getInfo=getInfo,
        tls=tls
    )

    server = Server(**vals)
    connection = Connection(server, authentication=authentication)
    # manager = ConnectionManager(**vals)

    def get_connector(request):
        registry = request.registry
        return Connector(registry, connection)
        #return Connector(registry, manager)

    config.set_request_property(get_connector, 'ldap_connector', reify=True)

    intr = config.introspectable(
        'pyramid_ldap setup',
        None,
        pprint.pformat(vals),
        'pyramid_ldap setup'
    )
    config.action('ldap-setup', None, introspectables=(intr,))


def get_ldap_connector(request):
    """ Return the LDAP connector attached to the request.  If
    :meth:`pyramid.config.Configurator.ldap_setup` was not called, using
    this function will raise an :exc:`pyramid.exceptions.ConfigurationError`."""
    connector = getattr(request, 'ldap_connector', None)
    if connector is None:
        raise ConfigurationError(
            'You must call Configurator.ldap_setup during setup '
            'to use an ldap connector')
    return connector


def groupfinder(userdn, request):
    """ A groupfinder implementation useful in conjunction with
    out-of-the-box Pyramid authentication policies.  It returns the DN of
    each group belonging to the user specified by ``userdn`` to as a
    principal in the list of results; if the user does not exist, it returns
    None."""
    connector = get_ldap_connector(request)
    group_list = connector.user_groups(userdn)
    if group_list is None:
        return None
    group_dns = []
    for dn, attrs in group_list:
        group_dns.append(dn)
    return group_dns


def _ldap_decode(result):
    """ Decode (recursively) strings in the result data structure to Unicode
    using the utf-8 encoding """
    return _Decoder().decode(result)


class _Decoder(object):
    """
    Stolen from django-auth-ldap.
    
    Encodes and decodes strings in a nested structure of lists, tuples, and
    dicts. This is helpful when interacting with the Unicode-unaware
    python-ldap.
    """

    ldap = ldap3

    def __init__(self, encoding='utf-8'):
        self.encoding = encoding

    def decode(self, value):
        try:
            if isinstance(value, list):
                value = self._decode_list(value)
            elif isinstance(value, tuple):
                value = tuple(self._decode_list(value))
            elif isinstance(value, dict):
                value = self._decode_dict(value)
        except UnicodeDecodeError:
            pass

        return value

    def _decode_list(self, value):
        return [self.decode(v) for v in value]

    def _decode_dict(self, value):
        # Attribute dictionaries should be case-insensitive. python-ldap
        # defines this, although for some reason, it doesn't appear to use it
        # for search results.
        # decoded = self.ldap.cidict.cidict()
        decoded = ObjectDef()

        for k, v in value.items():
            decoded += AttrDef(self.decode(v), key=self.decode(k))
            #decoded[self.decode(k)] = self.decode(v)

        return decoded


def includeme(config):
    """ Set up Configurator methods for pyramid_ldap """
    config.add_directive('ldap_setup', ldap_setup)
    config.add_directive('ldap_set_login_query', ldap_set_login_query)
    config.add_directive('ldap_set_groups_query', ldap_set_groups_query)

