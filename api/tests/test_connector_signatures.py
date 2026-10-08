"""Every registered connector is callable the way the sync calls it.

**`isinstance` against a Protocol is not enough**, and this file exists because
that gap shipped. A runtime-checkable Protocol checks that a method *exists*, not
that it accepts the arguments its callers pass — so `SnowflakeConnector` sat in
the registry, in the picker, with a logo, taking a positional `context` where the
base class takes a keyword-only `local`. Every call from `sync` raised
`TypeError: discover() got an unexpected keyword argument 'local'`.

It went unnoticed because `test_connection` *did* match: the Test button went
green, and the next step returned no columns — which looks exactly like a query
that found nothing.

So this compares signatures rather than names, against the call sites that
actually exist in `app/sync.py`.
"""

import inspect

import pytest

from app import connectors


def registered():
    return sorted(connectors._REGISTRY.items())


@pytest.mark.parametrize("key", [k for k, _ in registered()])
def test_discover_accepts_local_as_a_keyword(key):
    """`sync` calls `connector.discover(config, credentials, local=...)`."""
    sig = inspect.signature(connectors._REGISTRY[key].discover)
    bound = sig.bind(object(), object(), local=None)
    assert "local" in bound.arguments


@pytest.mark.parametrize("key", [k for k, _ in registered()])
def test_fetch_accepts_since_and_local(key):
    """`sync` calls `connector.fetch(config, credentials, since, local=...)`."""
    sig = inspect.signature(connectors._REGISTRY[key].fetch)
    bound = sig.bind(object(), object(), None, local=None)
    assert "local" in bound.arguments


@pytest.mark.parametrize("key", [k for k, _ in registered()])
def test_test_connection_takes_config_and_credentials(key):
    sig = inspect.signature(connectors._REGISTRY[key].test_connection)
    sig.bind(object(), object())


def test_snowflake_is_registered_and_callable():
    """Named, because it is the one this file was written for. A connector in the
    picker that cannot be called is worse than one that is absent: it looks like
    a working option right up until somebody depends on it."""
    assert "snowflake" in connectors._REGISTRY

    connector = connectors._REGISTRY["snowflake"]
    inspect.signature(connector.discover).bind(object(), object(), local=None)
    inspect.signature(connector.fetch).bind(object(), object(), None, local=None)
