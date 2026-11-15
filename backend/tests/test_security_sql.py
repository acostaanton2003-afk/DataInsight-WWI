"""Static SQL safety contracts only; does not execute or prove PostgreSQL semantics."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]/'database'/'security'


def sql(name):
    text=(ROOT/name).read_text(encoding='utf-8')
    return re.sub(r'--[^\n]*','',text).lower()


def test_role_schema_is_private_and_read_only():
    text=sql('01_roles_backend.sql')
    assert re.findall(r'create table\s+([\w.]+)',text)==['app_security.user_roles']
    assert 'references auth.users(id)' in text
    assert 'enable row level security' in text and 'force row level security' in text
    assert 'for select to wwi_backend_reader' in text
    assert "using (current_user = 'wwi_backend_reader')" in text
    assert 'backend_read_roles' in text
    assert 'app_security.user_id' not in text
    assert 'set_config' not in text
    assert 'using (true)' not in text
    assert 'grant select (user_id,role,enabled)' in text
    assert not re.search(r'grant\s+(insert|update|delete|truncate|all|create|execute)',text)
    assert not re.search(r'grant[^;]+to\s+(public|anon|authenticated)\b',text)
    assert 'alter default privileges in schema app_security' in text
    assert 'has_any_column_privilege' in text
    assert "d.defaclnamespace=0" in text
    assert 'pg_auth_members' in text
    assert 'insert into' not in text and 'create role' not in text
    assert not re.search(r'(alter|create|drop|truncate|delete)\s+(table|schema)?\s*dwh\.',text)
    assert text.strip().startswith('begin;') and text.strip().endswith('commit;')


def test_verification_and_rollback_preserve_data():
    verification=sql('02_verificar_roles_backend.sql')
    rollback=sql('03_revertir_acceso_roles.sql')
    assert 'begin read only' in verification and 'rollback;' in verification
    assert "row_security_active('app_security.user_roles'::regclass)" in verification
    assert 'has_column_privilege' in verification
    assert 'set_config' not in verification
    assert 'app_security.user_id' not in verification
    assert 'visible_without_subject' not in verification
    assert 'visible_role_assignments' in verification
    assert 'has_any_column_privilege' in rollback
    assert 'revoke select (user_id,role,enabled)' in rollback
    assert 'revoke usage on schema app_security' in rollback
    assert not re.search(r'(?m)^\s*(drop|truncate|delete|insert|update)\b',verification+rollback)


def test_role_lookup_has_no_session_identity_dependency():
    repository=(ROOT.parents[1]/'backend'/'app'/'role_repository.py').read_text(encoding='utf-8')
    assert 'SUBJECT_SQL' not in repository
    assert 'set_config' not in repository and 'current_setting' not in repository
    assert 'WHERE user_id = %s' in repository
