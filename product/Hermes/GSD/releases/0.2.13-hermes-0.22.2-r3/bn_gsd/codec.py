import hashlib
import json


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def read_json(text):
    def unique(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ValueError("Duplicate JSON key")
            result[k] = v
        return result
    def constant(value):
        raise ValueError("Non-finite JSON number")
    return json.loads(text, object_pairs_hook=unique, parse_constant=constant)


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for x in value.values():
            yield from strings(x)
    elif isinstance(value, (tuple, list)):
        for x in value:
            yield from strings(x)
