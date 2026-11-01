"""Identity operator workflow. Do not expose this command as a model tool."""
import argparse
import json
from pathlib import Path
from bnn_identity import Store
from bnn_identity.io import read_regular,save_new,encoded
from bnn_identity.owner import sign_receipt,export_template


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[2]/'authority/state-v2')
    commands=parser.add_subparsers(dest='command',required=True)
    commands.add_parser('status');commands.add_parser('verify')
    propose=commands.add_parser('propose')
    for key in ['profile','expected-revision','reason']:propose.add_argument('--'+key,required=True)
    propose.add_argument('--source',type=Path,required=True)
    sign=commands.add_parser('sign')
    sign.add_argument('--decision',choices=['accept','apply','rollback','cancel'],required=True)
    for key in ['revision','reviewed-sha256','reason']:sign.add_argument('--'+key,required=True)
    sign.add_argument('--expected-revision');sign.add_argument('--expected-sha256');sign.add_argument('--output',type=Path,required=True)
    for name in ['accept','apply','cancel']:
        command=commands.add_parser(name);command.add_argument('--receipt',type=Path,required=True)
    recover=commands.add_parser('recover');recover.add_argument('--intent',required=True)
    export=commands.add_parser('export-template');export.add_argument('--source',type=Path,required=True);export.add_argument('--destination',type=Path,required=True)
    args=parser.parse_args();store=Store(args.root)
    if args.command=='status':value=store.status()
    elif args.command=='verify':value=store.verify()
    elif args.command=='propose':
        revision=store.propose(args.profile,read_regular(args.source),expected_revision=args.expected_revision,reason=args.reason)
        value={'revision':revision,'source_sha256':store.revision(revision)['sha256'],'activated':False}
    elif args.command=='sign':
        receipt=sign_receipt(store,decision=args.decision,revision=args.revision,reviewed_sha256=args.reviewed_sha256,
                             reason=args.reason,expected_revision=args.expected_revision,expected_sha256=args.expected_sha256)
        save_new(args.output,encoded(receipt));value={'receipt_saved':str(args.output),'activated':False}
    elif args.command in {'accept','apply','cancel'}:
        result=getattr(store,args.command)(json.loads(read_regular(args.receipt)));value={'operation':args.command,'result':result}
    elif args.command=='recover':value={'recovered':store.recover(args.intent)}
    else:value=export_template(args.source,args.destination)
    print(json.dumps(value,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
