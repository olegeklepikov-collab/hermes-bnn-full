"""Operator-only source classification; no shell commands and no source content output."""
import argparse
import json
from pathlib import Path
from bn_memory.store import Store
from bn_memory.source_visibility import Visibility,hash_file,digest


def main(config_path,argv):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['inspect','classify'])
    identity=p.add_mutually_exclusive_group(required=True)
    identity.add_argument('--sha256');identity.add_argument('--file')
    p.add_argument('--expected-revision',type=int);p.add_argument('--policy-file')
    args=p.parse_args(argv)
    sha256=hash_file(Path(args.file).absolute()) if args.file else digest(args.sha256)
    config=json.loads(Path(config_path).read_text());store=Store(config['state_root'],config);access=Visibility(store)
    if args.action=='inspect':
        if args.expected_revision is not None or args.policy_file:p.error('inspect does not change policy')
        with store.db() as db:policy,revision=access.policy(db,sha256)
        value={'sha256':sha256,'revision':revision,'policy':policy,'default_parent_only':revision==0}
    else:
        if args.expected_revision is None or not args.policy_file:p.error('classify requires expected revision and policy file')
        body=json.loads(Path(args.policy_file).read_text())
        if set(body)-{'visibility','source_dependencies','reason'} or not {'visibility','reason'}<=set(body):
            raise ValueError('source_policy_file_contract_invalid')
        value=access.revise(sha256,args.expected_revision,body['visibility'],body['reason'],body.get('source_dependencies',[]))
    print(json.dumps(value,ensure_ascii=False,indent=2));return 0
