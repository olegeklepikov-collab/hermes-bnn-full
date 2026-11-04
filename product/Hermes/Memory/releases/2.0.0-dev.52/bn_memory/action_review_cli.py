"""Local operator command. Never register review/permit/revoke as model tools."""
import argparse
import json
from bn_memory.action_review import Reviews
from bn_memory.action_retry import UNKNOWN
from bn_memory.plugin import Host


def main(config_path, argv):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    pending = commands.add_parser('pending'); pending.add_argument('--offset', type=int, default=0); pending.add_argument('--limit', type=int, default=20)
    inspect = commands.add_parser('inspect'); inspect.add_argument('--nonce', required=True)
    review = commands.add_parser('review')
    for field in ['nonce', 'expected-attempt-sha256', 'operator', 'reason', 'evidence-file', 'evidence-sha256', 'request-id']:
        review.add_argument('--' + field, required=True)
    review.add_argument('--expected-revision', type=int, required=True)
    review.add_argument('--outcome', choices=['performed', 'not_performed', 'unknown'], required=True)
    review.add_argument('--external-quiescent', action='store_true')
    permit = commands.add_parser('permit')
    for field in ['nonce', 'target-sid', 'request-id']: permit.add_argument('--' + field, required=True)
    permit.add_argument('--review-revision', type=int, required=True)
    revoke = commands.add_parser('revoke'); revoke.add_argument('--permit-id', required=True)
    args = vars(parser.parse_args(argv)); action = args.pop('action')
    host = Host(config_path)
    try:
        reviews = Reviews(host.store)
        if action == 'pending':
            if args['offset'] < 0 or not 1 <= args['limit'] <= 100: raise ValueError('operator_page_invalid')
            with host.store.db() as db:
                values = (host.store.profile, *UNKNOWN)
                where = 'profile_id=? AND status IN (?,?,?,?)'
                total = db.execute('SELECT count(*) FROM action_attempts WHERE ' + where, values).fetchone()[0]
                rows = db.execute('SELECT nonce,sid,tool_name,effect,status FROM action_attempts WHERE ' + where + ' ORDER BY created,nonce LIMIT ? OFFSET ?', (*values,args['limit'],args['offset'])).fetchall()
            value = {'attempts': [dict(row) for row in rows], 'total_raw_unknown': total,
                     'next_offset': args['offset'] + args['limit'] if args['offset'] + args['limit'] < total else None,
                     'raw_history_kept_after_review': True}
        elif action == 'inspect': value = reviews.inspect(**args)
        elif action == 'review': value = reviews.review(**args)
        elif action == 'permit': value = reviews.permit(**args)
        else: value = reviews.revoke(args['permit_id'])
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0
    finally: host.close()
