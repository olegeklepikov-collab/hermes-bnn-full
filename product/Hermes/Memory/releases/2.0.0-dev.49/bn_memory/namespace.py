"""Explicit owner database and profile-local control state. No ambient-profile inference."""
from pathlib import Path
import re

TABLES = ('sessions', 'context_admissions', 'session_policy', 'launch_grants',
          'auxiliary_admissions', 'checkpoints', 'action_grants', 'action_attempts')


def configuration(config):
    value = config.get('namespace')
    if not isinstance(value, dict) or set(value) != {'owner_id', 'profile_id'}:
        raise ValueError('explicit_memory_namespace_required')
    for item in value.values():
        if not isinstance(item, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', item):
            raise ValueError('memory_namespace_identifier_invalid')
    home = config.get('profile_home')
    if not isinstance(home, str) or not Path(home).is_absolute():
        raise ValueError('explicit_memory_profile_home_required')
    return {**value, 'profile_home': str(Path(home).resolve())}


def install(connection, namespace):
    connection.execute("INSERT INTO meta VALUES('profile_namespace_contract','1')")
    connection.execute("INSERT INTO meta VALUES('owner_id',?)", (namespace['owner_id'],))
    connection.execute('CREATE TABLE profiles(profile_id TEXT PRIMARY KEY,profile_home TEXT NOT NULL UNIQUE)')
    connection.execute('INSERT INTO profiles VALUES(?,?)', (namespace['profile_id'], namespace['profile_home']))


def verify(connection, namespace):
    marker = connection.execute("SELECT value FROM meta WHERE key='profile_namespace_contract'").fetchone()
    if marker is None or marker[0] != '1':
        raise RuntimeError('explicit_profile_namespace_migration_required')
    owner = connection.execute("SELECT value FROM meta WHERE key='owner_id'").fetchone()
    if owner is None or owner[0] != namespace['owner_id']:
        raise PermissionError('memory_owner_namespace_mismatch')
    profile = connection.execute('SELECT profile_home FROM profiles WHERE profile_id=?', (namespace['profile_id'],)).fetchone()
    if profile is None or profile[0] != namespace['profile_home']:
        raise PermissionError('memory_profile_namespace_not_registered')


def register_profile(connection, owner_id, profile_id, profile_home):
    """Offline operator operation. No model tool or automatic registration on a read."""
    namespace = configuration({'namespace': {'owner_id': owner_id, 'profile_id': profile_id},
                               'profile_home': profile_home})
    owner = connection.execute("SELECT value FROM meta WHERE key='owner_id'").fetchone()
    if owner is None or owner[0] != owner_id:
        raise PermissionError('memory_owner_namespace_mismatch')
    old = connection.execute('SELECT profile_home FROM profiles WHERE profile_id=?', (profile_id,)).fetchone()
    if old:
        if old[0] != namespace['profile_home']:
            raise PermissionError('profile_relocation_requires_explicit_migration')
        return
    connection.execute('INSERT INTO profiles VALUES(?,?)', (profile_id, namespace['profile_home']))


def upgrade(connection, namespace, legacy_profile):
    """Assign legacy controls only to an explicitly attested originating profile."""
    if legacy_profile != namespace['profile_id']:
        raise PermissionError('explicit_legacy_origin_profile_required')
    from bn_memory.control_schema import install as create
    existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    columns = {}
    for table in TABLES:
        if table in existing:
            columns[table] = [row[1] for row in connection.execute('PRAGMA table_info(' + table + ')')]
            connection.execute('CREATE TEMP TABLE migration_' + table + ' AS SELECT * FROM ' + table)
            connection.execute('DROP TABLE ' + table)
    create(connection, *TABLES)
    install(connection, namespace)
    for table, names in columns.items():
        select = list(names)
        if table == 'session_policy':
            for name in ['gsd_revision', 'research_revision']:
                if name not in names:
                    names.append(name)
                    select.append('revision')
        connection.execute('INSERT INTO ' + table + '(' + ','.join(names) + ',profile_id) SELECT '
                           + ','.join(select) + ',? FROM migration_' + table, (namespace['profile_id'],))
        connection.execute('DROP TABLE migration_' + table)
