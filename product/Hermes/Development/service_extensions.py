"""Source-pinned additional providers; pending access never becomes an enabled call."""
from pathlib import Path
import copy,hashlib,json,re,time
import requests
from service_docs import ROOT,BASE,dump
from service_openapi import canonical,sha,convert_nullable,close_references,local_ref

WORK=ROOT/'Development/services-remediation-20261028'
DOCS=WORK/'sources'
NEW={
 'datacite':('DataCite','public_api','https://api.datacite.org',None),
 'tinyfish':('TinyFish','independent_BNN_oauth','https://agent.tinyfish.ai/mcp','independent_oauth_required'),
 'tinyfish-api':('TinyFish','api_key','https://agent.tinyfish.ai','api_key_required'),
 'wiley':('WileyScholarGateway','independent_BNN_oauth','https://connector.scholargateway.ai/v2/mcp','independent_oauth_required'),
 'scispace':('SciSpace','public_mcp','https://scispace.com/mcp-kls34hjb','published_endpoint_http_403'),
 'elicit':('Elicit','independent_BNN_oauth','https://elicit.com/api/mcp','eligible_plan_and_oauth_required'),
 'elicit-api':('Elicit','api_key','https://elicit.com/api/v2','eligible_plan_and_api_key_required'),
 'synapse':('Synapse','public_or_personal_token','https://repo-prod.prod.sagebase.org',None),
}
DATACITE=['get_dois','get_dois-id','get_clients','get_clients-id','get_clients-totals',
 'get_prefixes','get_prefixes-id','get_prefixes-totals','get_providers','get_providers-id',
 'get_providers-totals','get_events','get_events-id','get_heartbeat','get_client-prefixes','get_provider-prefixes']
SYNAPSE_READ={'/repo/v1/entity/{id}','/repo/v1/entity/{id}/version/{versionNumber}',
 '/repo/v1/entity/{id}/annotations2','/repo/v1/entity/{id}/version/{versionNumber}/annotations2',
 '/repo/v1/entity/{id}/path','/repo/v1/entity/{id}/version','/repo/v1/entity/{id}/generatedBy',
 '/repo/v1/entity/{id}/version/{versionNumber}/generatedBy','/repo/v1/entity/{id}/type',
 '/repo/v1/entity/{id}/permissions','/repo/v1/entity/{id}/accessRequirement',
 '/repo/v1/entity/{id}/column','/repo/v1/entity/{id}/filehandles',
 '/repo/v1/entity/{id}/version/{versionNumber}/filehandles',
 '/repo/v1/entity/{id}/table/query/async/get/{asyncToken}',
 '/repo/v1/entity/{id}/table/download/csv/async/get/{asyncToken}'}
SYNAPSE_QUERY={'/repo/v1/search','/repo/v1/entity/children'}
SYNAPSE_JOB={'/repo/v1/entity/{id}/table/query/async/start','/repo/v1/entity/{id}/table/download/csv/async/start'}

def acquire(url,service):
    key=hashlib.sha256(url.encode()).hexdigest();path=DOCS/(key+'.source');meta=DOCS/(key+'.json')
    if meta.exists():m=json.loads(meta.read_text())
    else:
        with requests.Session() as client:
            client.trust_env=False;r=client.get(url,timeout=(5,25));raw=r.content
        path.parent.mkdir(parents=True,exist_ok=True,mode=0o700);path.write_bytes(raw)
        m={'url':url,'http':r.status_code,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'file':path.name}
        dump(meta,m)
    if m.get('http')!=200:raise RuntimeError('official_source_unavailable: '+url)
    if hashlib.sha256(path.read_bytes()).hexdigest()!=m['sha256']:raise PermissionError('official_source_changed_on_disk')
    dest=BASE/'documentation'/service/(key+'.source');dest.parent.mkdir(exist_ok=True,parents=True)
    if not dest.exists():dest.write_bytes(path.read_bytes());dest.chmod(0o600)
    provenance={'service':service,'url':url,'http_status':200,'sha256':m['sha256'],'bytes':path.stat().st_size,
        'file':str(dest.relative_to(BASE)),'acquisition_time':time.time(),'complete_transport':True,
        'semantic_review':'API schema parsed completely; account availability requires actual response'}
    return path.read_text(),provenance

def prepare():
    """Fetch only explicit canonical references; no arbitrary site crawl."""
    sources=[];specs=[]
    for name in DATACITE:
        url='https://support.datacite.org/reference/'+name+'.md';text,record=acquire(url,'datacite')
        match=re.search(r'```json\s*(.*?)\s*```',text,re.S)
        if not match:raise ValueError('official_datacite_openapi_block_missing')
        spec=json.loads(match[1]);spec['servers']=[{'url':'https://api.datacite.org'}]
        specs.append({'service':'datacite','family':name.removeprefix('get_').replace('-','_'),'spec':spec,'source':record});sources.append(record)
    for family in ['main','search','fetch','research','monitor','browser']:
        url='https://agent.tinyfish.ai/v1/openapi/'+family;text,record=acquire(url,'tinyfish')
        specs.append({'service':'tinyfish-api','family':family,'spec':json.loads(text),'source':record});sources.append(record)
    text,record=acquire('https://docs.elicit.com/openapi.json','elicit')
    specs.append({'service':'elicit-api','family':'v2','spec':json.loads(text),'source':record});sources.append(record)
    text,record=acquire('https://rest-docs.synapse.org/rest/openapi/openapispecification.json','synapse')
    spec=json.loads(text);all_paths=len(spec['paths']);spec['paths']={p:v for p,v in spec['paths'].items() if p in SYNAPSE_READ|SYNAPSE_QUERY|SYNAPSE_JOB}
    specs.append({'service':'synapse','family':'research','spec':spec,'source':record,'supplier_paths':all_paths,'selected_paths':len(spec['paths'])});sources.append(record)
    dump(WORK/'specifications.json',specs)
    ledger=json.loads((BASE/'documentation-ledger.json').read_text());seen={x['url'] for x in ledger['sources']}
    ledger['sources'] += [x for x in sources if x['url'] not in seen]
    dump(BASE/'documentation-ledger.json',ledger)
    reg=json.loads((ROOT/'Services/registry.private.json').read_text());names={e['service'] for e in reg['services']}
    for name,(folder,authentication,url,hold) in NEW.items():
        if name in names:continue
        root=ROOT/'Services/software'/folder;root.mkdir(exist_ok=True,parents=True,mode=0o700)
        authority=ROOT/'state/authority/services'/(name+'.json')
        if not authority.exists():dump(authority,{'headers':{},'env':{}})
        entry={'service':name,'directory':folder,'legacy_enabled':False,'legacy_tool_filter':{},
            'transport':'http','state_root':str(root),'authentication':authentication,
            'credential_present':False,'discovery':'source_pinned_or_pending_live_catalogue','tool_timeout':240,
            'url':url,'authority_file':str(authority),'env':{}}
        if authentication=='independent_BNN_oauth':entry['oauth']={'client_name':'Hermes BNN — '+folder,'timeout':900}
        if hold:entry['connection_hold']=hold
        reg['services'].append(entry)
        p=BASE/'catalogues'/(name+'.json')
        if not p.exists():dump(p,{'ok':False,'code':hold or 'documented_REST_adapter','tools':[],'source':'Official live API schema; not invented MCP tools'})
    dump(WORK/'registry.candidate.private.json',reg)
    result={'ok':True,'source_specs':len(specs),'new_connectors':len(NEW),'account_authorizations_performed':False,
        'datacite_public':True,'synapse_scope':'Selected research read/query APIs, not 510 administrative/account endpoints'}
    dump(WORK/'preparation.json',result);return result

def category(service,family,verb,path):
    p=path.lower()
    if service=='datacite':return 'read' if verb=='get' else 'blocked'
    if service=='synapse':
        if verb=='get' and path in SYNAPSE_READ:return 'read'
        if verb=='post' and path in SYNAPSE_QUERY:return 'read'
        if verb=='post' and path in SYNAPSE_JOB:return 'job'
        return 'blocked'
    if service=='tinyfish-api':
        if '/vault' in p or '/wallet/top-up' in p or '/events' in p or 'run-sse' in p:return 'blocked'
        if family=='browser':return 'blocked' # CDP capability needs a confined executor, not model-visible credentials.
        if verb=='get':return 'read'
        if family in {'search','fetch'}:return 'read'
        if family=='research' and 'async' in p:return 'job'
        if 'run-research' in p:return 'blocked' # This endpoint always streams, even stream=false.
        return 'write' # Browser goals and permanent monitors require exact owner approval.
    if service=='elicit-api':
        if '/events' in p:return 'blocked'
        if verb=='get':return 'read'
        if path in ['/search/papers','/search/trials']:return 'read'
        if verb=='post' and (path in ['/sessions/reports','/sessions/systematic-reviews','/sessions/agents'] or p.endswith(('/resume','/messages','/run'))):return 'job'
        return 'write'
    return 'blocked'

def augment(catalogue):
    path=WORK/'specifications.json'
    if not path.exists():return []
    records=[]
    for bundle in json.loads(path.read_text()):
        service=bundle['service'];spec=bundle['spec'];family=bundle['family'];source=bundle['source']
        if service not in catalogue['services']:continue
        methods=catalogue['services'][service]['methods']
        for path,entries in spec['paths'].items():
            for verb,operation in entries.items():
                if verb not in {'get','post','put','patch','delete'}:continue
                op=local_ref(spec,operation);oid=op.get('operationId') or verb+'_'+path
                name='api_'+family+'_'+re.sub('[^A-Za-z0-9_]+','_',oid).strip('_')
                if len(name)>125:name=name[:100]+'_'+sha(name)[:16]
                if name in methods:raise ValueError('duplicate_extension_operation')
                properties={};required=[];locations={};unsupported=[]
                for param in entries.get('parameters',[])+op.get('parameters',[]):
                    param=local_ref(spec,param);location=param['in'];n=param['name']
                    if location not in {'path','query','header'}:unsupported.append('parameter_location:'+location);continue
                    if n.lower() in {'authorization','x-api-key','cookie','authtoken','api_key','access_token'}:continue
                    section=properties.setdefault(location,{'type':'object','properties':{},'additionalProperties':False})
                    section['properties'][n]=convert_nullable(param.get('schema',{}))
                    locations.setdefault(location,[]).append({'name':n,'style':param.get('style'),'explode':param.get('explode',True)})
                    if param.get('required'):section.setdefault('required',[]).append(n)
                if op.get('requestBody'):
                    body=local_ref(spec,op['requestBody']);content=body.get('content',{})
                    if 'application/json' in content:properties['body']=convert_nullable(content['application/json'].get('schema',{}))
                    else:unsupported.append('multipart_or_binary_input_requires_file_adapter')
                    if body.get('required'):required.append('body')
                for section in ['path','query','header']:
                    if properties.get(section,{}).get('required'):required.append(section)
                schema={'type':'object','properties':properties,'required':required,'additionalProperties':False}
                try:schema=close_references(schema,convert_nullable(spec))
                except (KeyError,ValueError):unsupported.append('unclosed_schema_dependency')
                effect=category(service,family,verb,path)
                if unsupported:effect='blocked'
                methods[name]={'description':op.get('summary',op.get('description',''))+'; '+verb.upper()+' '+path,
                    'input_schema':schema,'schema_sha256':sha(canonical(schema)),'effect':effect,
                    'api_request':{'method':verb.upper(),'base':spec['servers'][0]['url'].rstrip('/'),'path':path,'parameters':locations},
                    'source_url':source['url'],'source_sha256':source['sha256'],'unsupported':unsupported,
                    'implementation':'Pinned published API; trusted BNN transport and native control; no invented MCP schema','semantic_test':'not_run'}
        records.append({'service':service,'family':family,'url':source['url'],'source_sha256':source['sha256'],
            'paths':len(spec['paths']),'supplier_paths':bundle.get('supplier_paths',len(spec['paths'])),'every_selected_schema_parsed':True})
    return records

def status():
    cfg=json.loads((ROOT/'Memory/settings.json').read_text());reg=json.loads(Path(cfg['service_integration']['registry_file']).read_text())
    catalogue_file=Path(cfg['package_root'])/'services/catalogue.json'
    catalog=json.loads(catalogue_file.read_text())['services'];rows=[];latest={}
    import sqlite3
    with sqlite3.connect((Path(cfg['state_root'])/'memory.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        records=db.execute('SELECT state,body,receipt FROM service_results ORDER BY rowid') if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='service_results'").fetchone() else []
        for state,body,receipt in records:
            r=json.loads(receipt or '{}');name=r.get('service')
            if not name:continue
            try:value=json.loads(body or '{}')
            except ValueError:value={}
            latest[name]={'method':r.get('method'),'state':state,'provider_error_indicator':r.get('is_error'),
                'http_status':value.get('http_status'),'meaning':'Last retained observation, not a fresh availability probe or scientific acceptance.'}
    for entry in reg['services']:
        name=entry['service'];cat=catalog.get(name,{'methods':{}});oauth=(ROOT/'data/mcp-tokens'/(name+'.json')).is_file()
        rows.append({'service':name,'declared_methods':len(cat['methods']),'enabled_methods':sum(x['effect']!='blocked' for x in cat['methods'].values()),
            'connection_hold':entry.get('connection_hold'),'oauth_store_present':oauth,
            'credential_saved_flag':entry.get('credential_present',False),'catalog_status':cat.get('status'),
            'last_observed_call':latest.get(name),'live_account_availability':'not_verified_by_status_observation'})
    valid=hashlib.sha256(Path(cfg['service_integration']['registry_file']).read_bytes()).hexdigest()==cfg['service_integration']['registry_sha256'] and hashlib.sha256(catalogue_file.read_bytes()).hexdigest()==cfg['service_integration']['catalogue_sha256']
    return {'runtime':Path(cfg['package_root']).name,'configuration_matches_pins':valid,'services':rows,'secret_values_included':False}

def stage_registry():
    from service_lifecycle import quiescent,stop_for_cutover
    cfg=json.loads((ROOT/'Memory/settings.json').read_text());quiescent(cfg)
    state=stop_for_cutover();dump(WORK/'cutover-before.json',state)
    value=json.loads((WORK/'registry.candidate.private.json').read_text())
    dump(ROOT/'Services/registry.private.json',value)
    return {'registry_staged':True,'gateway_stopped_for_own_cutover':True,'production_BN_UDR_changed':False}
