"""Versioned record attributes; scope, horizon, type and analytical visibility are distinct."""
import datetime as dt
import hashlib
import json

HORIZONS = ('long_term', 'working', 'operational', 'unclassified')
MEMORY_TYPES = ('semantic', 'episodic', 'procedural', 'prospective', 'documentary', 'metamemory', 'unclassified')
ROLES = ('parent', 'collector', 'analyst', 'reviewer', 'G', 'S', 'D', 'parser', 'computation')
FIELDS = {'horizon', 'memory_type', 'event_time', 'valid_from', 'valid_to', 'classification_reason', 'visibility', 'source_dependencies'}
LEGACY_FIELDS = {'content', 'source_ref', 'kind', 'request_id', 'scope', 'concepts', 'id', 'expected_revision'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def time_value(value):
    if value is None:
        return None
    if not isinstance(value, str) or not 4 <= len(value) <= 40:
        raise ValueError('memory_time_invalid')
    try:
        if len(value) == 4:
            dt.date(int(value), 1, 1)
        elif len(value) == 7:
            dt.date.fromisoformat(value + '-01')
        elif len(value) == 10:
            dt.date.fromisoformat(value)
        else:
            parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise ValueError('timezone_required')
    except (ValueError, TypeError) as exc:
        raise ValueError('memory_time_invalid') from exc
    return value


def attributes(args):
    if set(args) - LEGACY_FIELDS - FIELDS:
        raise ValueError('unknown_memory_record_field')
    horizon, kind = args.get('horizon', 'unclassified'), args.get('memory_type', 'unclassified')
    if horizon not in HORIZONS or kind not in MEMORY_TYPES:
        raise ValueError('memory_classification_invalid')
    reason = args.get('classification_reason', 'not_classified_by_source')
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 1024:
        raise ValueError('classification_reason_required')
    visibility = args.get('visibility', {'allowed_roles': ['parent'], 'evidence_use': 'unclassified'})
    if not isinstance(visibility, dict) or set(visibility) != {'allowed_roles', 'evidence_use'}:
        raise ValueError('visibility_contract_invalid')
    roles = visibility['allowed_roles']
    if (not isinstance(roles, list) or not roles or len(set(roles)) != len(roles)
            or any(role not in ROLES for role in roles)):
        raise ValueError('visibility_roles_invalid')
    use = visibility['evidence_use']
    if use not in {'unclassified', 'generation', 'verification', 'general'}:
        raise ValueError('evidence_use_invalid')
    if use == 'verification' and 'G' in roles:
        raise ValueError('holdout_cannot_be_visible_to_G')
    result = {'horizon': horizon, 'memory_type': kind, 'classification_reason': reason,
              'visibility': {'allowed_roles': sorted(roles), 'evidence_use': use}}
    result.update({field: time_value(args.get(field)) for field in ['event_time', 'valid_from', 'valid_to']})
    start, end = result['valid_from'], result['valid_to']
    if start and end and len(start) == len(end) and len(start) in {4, 7, 10} and end < start:
        raise ValueError('validity_range_invalid')
    if start and end and len(start)>10 and len(end)>10:
        if dt.datetime.fromisoformat(end.replace('Z','+00:00')) < dt.datetime.fromisoformat(start.replace('Z','+00:00')):
            raise ValueError('validity_range_invalid')
    if 'source_dependencies' in args:
        from bn_memory.source_visibility import dependencies
        result['source_dependencies'] = dependencies(args['source_dependencies'])
    return result


def install(connection):
    connection.execute('''CREATE TABLE record_metadata(
        id TEXT NOT NULL, revision INTEGER NOT NULL, attributes TEXT NOT NULL, attributes_hash TEXT NOT NULL,
        PRIMARY KEY(id,revision), FOREIGN KEY(id,revision) REFERENCES records(id,revision))''')
    existing={row[1] for row in connection.execute('PRAGMA table_info(sessions)')}
    for name,default in [('role','parent'),('purpose',''),('assignment_id','')]:
        if name not in existing:
            connection.execute("ALTER TABLE sessions ADD COLUMN "+name+" TEXT NOT NULL DEFAULT '"+default+"'")
    connection.execute("UPDATE sessions SET role='unassigned',context=NULL,turn=NULL WHERE readonly=1")
    default = attributes({})
    for row in connection.execute('SELECT id,revision FROM records').fetchall():
        insert(connection, row[0], row[1], default)


def insert(connection, identifier, revision, value):
    raw = canonical(value)
    connection.execute('INSERT INTO record_metadata VALUES(?,?,?,?)',
                       (identifier, revision, raw, hashlib.sha256(raw.encode()).hexdigest()))


def read(connection, identifier, revision):
    row = connection.execute('SELECT attributes,attributes_hash FROM record_metadata WHERE id=? AND revision=?',
                             (identifier, revision)).fetchone()
    if not row or hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
        raise RuntimeError('record_metadata_integrity_failed')
    return json.loads(row[0])


def enforce(binding, value):
    if not binding['readonly']:
        return
    role = binding['role']
    if not binding['assignment_id'] or role not in ROLES:
        raise PermissionError('child_assignment_required')
    visibility = value['visibility']
    if role not in visibility['allowed_roles'] or role == 'G' and visibility['evidence_use'] == 'verification':
        raise PermissionError('record_not_visible_to_analytical_role')


def search_filter(binding):
    if not binding['readonly']:
        return '', []
    if not binding['assignment_id'] or binding['role'] not in ROLES:
        raise PermissionError('child_assignment_required')
    role = binding['role']
    sql = " AND EXISTS(SELECT 1 FROM json_each(m.attributes,'$.visibility.allowed_roles') WHERE value=?)"
    if role == 'G':
        sql += " AND json_extract(m.attributes,'$.visibility.evidence_use')!='verification'"
    from bn_memory.assignment_resources import sql_filter
    extra,params=sql_filter(binding)
    return sql+extra, [role]+params
