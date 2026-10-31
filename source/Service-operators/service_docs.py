"""Reproducible official-document corpus. Acquisition is not semantic acceptance."""
from pathlib import Path
import concurrent.futures, hashlib, json, re, time
from urllib.parse import urljoin,urlsplit
import requests

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'Development/services-20261028'
SEEDS={
 'firecrawl':['https://docs.firecrawl.dev/llms.txt','https://docs.firecrawl.dev/_llms/en/v2.txt','https://docs.firecrawl.dev/api-reference/v2-openapi.json'],
 'exa':['https://exa.ai/docs/llms.txt','https://exa.ai/docs/exa-spec.yaml'],
 'tavily':['https://docs.tavily.com/llms.txt','https://docs.tavily.com/llms-full.txt'],
 'keenable':['https://docs.keenable.ai/llms.txt'],
 'nimble':['https://docs.nimbleway.com/llms.txt'],
 'parallel':['https://docs.parallel.ai/llms.txt'],
 'consensus':['https://docs.consensus.app/','https://consensus.app/home/mcp/'],
 'scite':['https://scite.ai/mcp','https://api.scite.ai/docs'],
 'undermind':['https://www.undermind.ai/mcp'],
 'alphaxiv':['https://www.alphaxiv.org/docs/mcp','https://www.alphaxiv.org/llms.txt','https://api.alphaxiv.org/mcp/v1'],
 'semanticscholar':['https://api.semanticscholar.org/api-docs/graph','https://api.semanticscholar.org/api-docs/recommendations','https://api.semanticscholar.org/api-docs/datasets'],
 'pubmed':['https://www.ncbi.nlm.nih.gov/books/NBK25501/','https://www.ncbi.nlm.nih.gov/pmc/tools/developers/'],
 'russianresearch':['https://elibrary.ru/projects/subscription/terms.asp','https://cyberleninka.ru/terms','https://www.dissercat.com/'],
 'webofscience':['https://developer.clarivate.com/apis/wos-starter','https://developer.clarivate.com/about/terms'],
 'pendar':['https://pendar.ai/docs/','https://pendar.ai/mcp'],
 'scholarsidekick':['https://scholar-sidekick.com/docs','https://scholar-sidekick.com/openapi/openapi.yml','https://scholar-sidekick.com/','https://scholar-sidekick.com/mcp'],
 'wolfram':['https://support.wolfram.com/75237','https://www.wolfram.com/ai/mcp/cloud/wolfram-mcp-cloud/','https://agenttools.wolfram.com/llms.txt','https://reference.wolfram.com/language/'],
 'rstats':['https://cran.r-project.org/manuals.html','https://cran.r-project.org/web/packages/btw/index.html'],
 'zotero':['https://www.zotero.org/support/dev/web_api/v3/start','https://www.zotero.org/support/dev/web_api/v3/basics','https://www.zotero.org/support/dev/client_coding'],
 'crossref':['https://www.crossref.org/documentation/retrieve-metadata/rest-api/','https://api.crossref.org/swagger-ui/index.html'],
 'openalex':['https://docs.openalex.org/llms.txt','https://developers.openalex.org/llms.txt','https://help.openalex.org/llms.txt'],
 'asreview':['https://asreview.readthedocs.io/en/stable/','https://asreview.ai/documentation/'],
 'beads':['https://raw.githubusercontent.com/steveyegge/beads/main/README.md'],
 'dolt':['https://docs.dolthub.com/llms.txt'],
}
DIRECTORIES={'semanticscholar':'SemanticScholar','pubmed':'PubMed','russianresearch':'RussianResearch','webofscience':'WebOfScience','scholarsidekick':'ScholarSidekick','rstats':'R','alphaxiv':'AlphaXiv','openalex':'OpenAlex','asreview':'ASReview','firecrawl':'Firecrawl','exa':'Exa','tavily':'Tavily','keenable':'Keenable','nimble':'Nimble','parallel':'Parallel','consensus':'Consensus','scite':'Scite','undermind':'Undermind','pendar':'Pendar','wolfram':'Wolfram','zotero':'Zotero','crossref':'Crossref','beads':'Beads','dolt':'Dolt'}
DIRECTORIES.update(datacite='DataCite',tinyfish='TinyFish',wiley='WileyScholarGateway',scispace='SciSpace',elicit='Elicit',synapse='Synapse')
SEEDS.update(datacite=['https://support.datacite.org/docs/rest-api'],tinyfish=['https://docs.tinyfish.ai/llms.txt'],wiley=['https://claude.com/marketplace/connectors/scholar-gateway?product=claude-cowork'],scispace=['https://claude.com/marketplace/connectors/scispace'],elicit=['https://docs.elicit.com/openapi.json'],synapse=['https://rest-docs.synapse.org/rest/'])
def dump(p,value):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');p.chmod(0o600)
def clean_url(url):
 p=urlsplit(url.strip('"\',.;'))
 return p._replace(fragment='').geturl() if p.scheme=='https' and not p.query and not p.username else None
def historical_urls(service):
 root=ROOT/DIRECTORIES[service]/'источники';out=set()
 if not root.exists():return out
 # Only explicit provenance labels, never arbitrary research results or user-account links.
 for p in root.glob('*'):
  if p.is_file() and p.suffix in {'.txt','.md','.json','.yaml'} and p.stat().st_size<2000000:
   t=p.read_text(errors='replace')
   for u in re.findall(r'(?im)^(?:URL|Source|Источник)\s*:\s*[`\s]*(https://[^\s`<>]+)',t):
    u=clean_url(u)
    if u and not any(x in u for x in ['/projects/','/app/','/api-keys','/settings/','/login','/signin','/signup']):out.add(u)
 return out
def fetch(item):
 service,url=item;key=hashlib.sha256(url.encode()).hexdigest();folder=BASE/'documentation'/service;path=folder/(key+'.source')
 if path.exists() and (folder/(key+'.json')).exists():return json.loads((folder/(key+'.json')).read_text())
 record={'service':service,'url':url,'acquisition_time':time.time(),'semantic_review':'not_established_by_download'}
 try:
  with requests.Session() as s:
   s.trust_env=False
   with s.get(url,timeout=(8,18),stream=True,headers={'User-Agent':'Hermes-BNN-documentation-review/1.0'}) as r:
    record.update(http_status=r.status_code,final_url=r.url,content_type=r.headers.get('content-type',''));data=bytearray()
    for b in r.iter_content(65536):
     data.extend(b)
     if len(data)>16*1024*1024:raise ValueError('documentation_exceeds_16MiB_not_truncated')
    record.update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    folder.mkdir(parents=True,exist_ok=True);path.write_bytes(data);path.chmod(0o600)
    record['file']=str(path.relative_to(BASE));record['complete_transport']=True
 except Exception as e:record.update(error=type(e).__name__,complete_transport=False)
 dump(folder/(key+'.json'),record);return record
def harvest():
 BASE.mkdir(parents=True,exist_ok=True);ledger=[];seen=set();pending=[]
 for service,seeds in SEEDS.items():
  for u in set(seeds)|historical_urls(service):pending.append((service,u))
 allowed={k:{urlsplit(u).hostname for u in v}|{urlsplit(u).hostname for u in historical_urls(k)} for k,v in SEEDS.items()}
 # Finite indexed traversal; no arbitrary hyperlink crawl or translated copies.
 for wave in range(8):
  batch=sorted(set(pending)-seen);pending=[]
  if not batch:break
  seen.update(batch)
  with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
   for rec in ex.map(fetch,batch):
    ledger.append(rec)
    if rec.get('http_status')!=200 or not rec.get('file'):continue
    u=rec['url'];text=(BASE/rec['file']).read_text(errors='replace')
    if 'llms' in u and not 'llms-full' in u:
     for link in re.findall(r'\]\(([^)\s]+)\)',text):
      full=clean_url(urljoin(rec.get('final_url',u),link))
      if full and urlsplit(full).hostname in allowed[rec['service']] and not any(x in full for x in ['/_llms/es','/_llms/fr','/_llms/ja','/_llms/zh','/_llms/pt','/v0/']):pending.append((rec['service'],full))
    # Structural processing consumes the complete page, does not certify scientific correctness.
    headings=re.findall(r'(?m)^#{1,6}\s+(.+)$',text)
    endpoints=re.findall(r'(?m)\b(GET|POST|PUT|PATCH|DELETE)\s+(/[^\s`<>]+)',text)
    dump(BASE/'documentation'/rec['service']/(hashlib.sha256(u.encode()).hexdigest()+'.structure.json'),{'source_sha256':rec['sha256'],'characters_processed':len(text),'headings':headings,'endpoints':endpoints,'semantic_acceptance':False})
  dump(BASE/'documentation-ledger.json',{'sources':ledger,'pending':pending,'indexed_traversal_complete':not pending,'scope':'Official technical documentation, current English canonical indexes plus explicit legacy provenance; account/research content excluded.'})
  print(json.dumps({'documentation_wave':wave,'acquired':len(ledger),'remaining_index_links':len(set(pending)-seen)},ensure_ascii=False),flush=True)
 return {'acquired':len(ledger),'indexed_traversal_complete':not(set(pending)-seen),'services':len(SEEDS)}
if __name__=='__main__':print(json.dumps(harvest(),ensure_ascii=False))
