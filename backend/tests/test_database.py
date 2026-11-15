from pathlib import Path
from unittest.mock import MagicMock

import psycopg
import pytest

from backend.app.config import ReadOnlyDatabaseSettings
from backend.app.database import DatabaseReadError, REFERENCE_COUNTS, probe, read_connection


def config(**extra):
    values = dict(host='example.invalid',name='fixture',user='wwi_backend_reader',password='fake-secret')
    values.update(extra)
    return ReadOnlyDatabaseSettings(**values)


def factory(rows):
    connect = MagicMock()
    connection = connect.return_value.__enter__.return_value
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.side_effect = rows
    return connect,connection


def test_connection_uses_separate_ssl_parameters_and_closes():
    connect,connection=factory([('wwi_backend_reader',False,False,False,False,False)])
    with read_connection(config(),connect=connect) as actual:
        assert actual is connection
        assert connection.read_only is True
    kwargs=connect.call_args.kwargs
    assert kwargs['sslmode']=='require'
    assert kwargs['connect_timeout']==10
    assert 'default_transaction_read_only=on' in kwargs['options']
    assert kwargs['password']=='fake-secret'
    assert not connect.call_args.args
    connect.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize('extra',[{'password':''},{'host':''},{'user':'other_reader'}])
def test_incomplete_or_unexpected_role_never_connects(extra):
    connect=MagicMock()
    with pytest.raises(ValueError):
        with read_connection(config(**extra),connect=connect):
            pass
    connect.assert_not_called()


def test_driver_failure_is_sanitized():
    connect=MagicMock(side_effect=psycopg.OperationalError('fake-secret sensitive host'))
    with pytest.raises(DatabaseReadError) as error:
        with read_connection(config(),connect=connect):
            pass
    assert 'fake-secret' not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize('role',[('postgres',False,False,False,False,False),('wwi_backend_reader',False,True,False,False,False)])
def test_privileged_effective_role_is_rejected(role):
    connect,_=factory([role])
    with pytest.raises(DatabaseReadError):
        with read_connection(config(),connect=connect):
            pytest.fail('unsafe connection yielded')


def probe_rows(counts=REFERENCE_COUNTS,active=True):
    rows=[('wwi_backend_reader',False,False,False,False,False),('wwi_backend_reader','fixture')]
    for count in counts:
        rows.extend([(active,),(count,)])
    return rows


def test_probe_checks_actual_visibility():
    connect,_=factory(probe_rows())
    result=probe(config(),connect=connect)
    assert result['status']=='ok'
    assert sum(result['counts'].values())==304001


@pytest.mark.parametrize('rows',[probe_rows((0,0,0,0,0)),probe_rows(active=False)])
def test_probe_rejects_default_deny_or_inactive_rls(rows):
    connect,_=factory(rows)
    with pytest.raises(DatabaseReadError):
        probe(config(),connect=connect)


def test_sql_artifacts_keep_security_changes_separate():
    root=Path(__file__).resolve().parents[2]/'database'/'data-warehouse'
    grants=(root/'05_rol_backend_lectura.sql').read_text(encoding='utf-8')
    policies=(root/'06_propuesta_rls_backend.sql').read_text(encoding='utf-8')
    assert 'NOBYPASSRLS' in grants and 'NOINHERIT' in grants
    assert 'CREATE POLICY' not in grants
    assert 'FOR SELECT TO wwi_backend_reader USING (true)' in policies
    for text in (grants,policies):
        assert 'DISABLE ROW LEVEL SECURITY' not in text
        assert 'PASSWORD' not in text
