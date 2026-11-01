import argparse, asyncio, json, sys
from pathlib import Path
from api import P, MCP_URL, TOOL_NAMES, load, save, save_artifact, request

parser = argparse.ArgumentParser(prog='wolfram-bn')
parser.add_argument('command', choices=['status', 'catalog', 'profiles', 'call', 'batch'])
parser.add_argument('--name')
parser.add_argument('--profile')
parser.add_argument('--params', type=Path)
parser.add_argument('--output', type=Path)
parser.add_argument('--artifact-file', type=Path)
args = parser.parse_args()
try:
    params = load(args.params) if args.params else {}
    profiles = load(P / 'config/profiles.json')
    if args.profile:
        profile = profiles[args.profile]
        args.command = 'call'
        args.name = profile['name']
        params = {**profile.get('arguments', {}), **params}
    if args.command == 'status':
        result = {'provider': 'Wolfram Cloud MCP', 'mcp_url': MCP_URL,
                  'mode': 'anonymous_stateless', 'api_key_used': False,
                  'tools': TOOL_NAMES, 'profiles': len(profiles),
                  'verification': load(P / 'config/verification.json') if (P / 'config/verification.json').exists() else {}}
    elif args.command == 'profiles':
        result = profiles
    else:
        result = asyncio.run(request(args.command, args.name, params))
    if args.artifact_file:
        print('artifact', save_artifact(args.artifact_file, result))
    if args.output:
        save(args.output, result)
        print(args.output)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get('ok') is False or result.get('isError'):
        sys.exit(2)
except Exception as error:
    while isinstance(error, BaseExceptionGroup) and error.exceptions:
        error = error.exceptions[0]
    print(json.dumps({'ok': False, 'error_type': type(error).__name__,
                      'error': str(error)[:2000]}, ensure_ascii=False), file=sys.stderr)
    sys.exit(2)
