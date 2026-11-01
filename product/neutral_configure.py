"""Protected local input; no credentials in arguments, logs or distribution."""
import argparse,getpass,json,os,subprocess,sys
from pathlib import Path
from neutral_prepare import save

def main():
    parser=argparse.ArgumentParser();parser.add_argument('service',choices=['voyage','exa','parallel','keenable','firecrawl']);args=parser.parse_args()
    root=Path(__file__).resolve().parent/'Hermes';path=root/'Memory/settings.json';cfg=json.loads(path.read_text())
    for marker in (root/'state/services').glob('*.pid.json'):
        item=json.loads(marker.read_text());state=subprocess.run(['/bin/ps','-p',str(item['pid']),'-o','stat='],capture_output=True,text=True).stdout.strip()
        if state and not state.startswith('Z'):raise PermissionError('Stop this installation services before configuring credentials')
    service=args.service;out=Path(cfg['voyage_key_file']) if service=='voyage' else root/'private/research-providers'/(service+'.key')
    if out.exists():raise FileExistsError('Existing credential preserved; explicit rotation is separate')
    secret=getpass.getpass(service+' API key (hidden): ').strip()
    if len(secret)<12 or any(c.isspace() for c in secret):raise ValueError('Invalid key syntax; nothing saved')
    out.parent.mkdir(parents=True,exist_ok=True,mode=0o700);fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as stream:stream.write(secret+'\n');stream.flush();os.fsync(stream.fileno())
    sys.path.insert(0,cfg['package_root'])
    if service=='voyage':
        from bn_memory.backend_policy import resource_hash
        cfg['backend_policy']['allow']['embedding']['resource_sha256']=resource_hash(cfg,'embedding')
    else:
        from bn_memory.research_providers import resource_hash
        cfg.setdefault('research_providers',{'version':1,'providers':{}})['providers'][service]={'key_file':str(out)}
        cfg['research_providers']['providers'][service]['resource_sha256']=resource_hash(cfg,service)
    save(path,cfg)
    print('Credential saved locally. Actual connection still requires a successful native call; no external request was made.')
if __name__=='__main__':main()
