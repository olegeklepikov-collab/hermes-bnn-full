"""Точная адресация источников и сборка нормативного контекста.
Маршрут определяется семейством операции и её точным адресом, не ключевыми словами.
Наличие адреса/текста не является доказательством смыслового применения агентом.
"""
from __future__ import annotations
import json,hashlib,re
from pathlib import Path
from typing import Iterable, Any
from functools import lru_cache
from _base import ROOT,digest,load_json
@lru_cache(maxsize=12)
def _read_static_contract(path,mtime_ns,size):
    # Только неизменяемые нормативные данные; записи случая не кэшируются.
    return load_json(Path(path))

def static_contract(path):
    stat=path.stat()
    return _read_static_contract(str(path),stat.st_mtime_ns,stat.st_size)

FILES={'strict':'Строгое мышление (монолит).md','generative':'Генератор мышления (монолит).md',
       'delivery':'deep_agent_personality_project_management.md','engineering':'deep_agent_personality_ai_agents_engineer.md'}
PAT=r'(?:GC-[A-Z]\d{3}|C-[A-Z]\d{3}|GD\d+-\d{3}|D\d+-\d{3}|GA-\d{2}|GN\d{3}|P\d{3}|GG\d{2}|GP\d{2}|GS\d{2}|GX\d{2}|GE\d{3}|E\d{3}|GNG\d+|GR\d+|GU-\d{2}|GD\d+|GM\d+|GQ\d+|UGC-\d+|CR-\d+|NG\d+|R\d+|T\d{2}|G\d{2}|S\d+|D\d+|M\d+|Q\d+|C\d{2}|КЛ-\d+|ДК-\d+|ТЕСТ-\d+|ДР-\d+|ВО-\d+|ЛВ-\d+|ВК-\d+|ДЕФ-\d+|СД-\d+|РС-\d+|РСС-\d+|ВЛ-\d+|ФО-\d+|ИНЖ-\d+|ЭП-\d+|МД-\d+)'

def role_for(source,identifier):
    if source=='generative':
        controls={'GC-A001','GC-A002','GC-A004','GC-A005','GC-A007','GC-A008','GC-C008','GC-D008','GC-E008','GC-F006','GC-F007','GC-F008','GC-G008','GC-H008','GC-H010'}
        if identifier in controls:return 'generation_control'
        if identifier.startswith('GC-J'):return 'generation_selection_or_handoff'
        if re.fullmatch(r'(GC-[A-Z]\d{3}|GA-\d{2})',identifier):return 'generation'
        if re.fullmatch(r'(GN\d{3}|GD\d+-\d{3})',identifier):return 'generative_principle'
        for prefix,role in [('GQ','quality'),('GM','method'),('GG','generation_review'),('GP','generation_protocol'),('GS','generation_status'),('GD','direction'),('GU','variation_axis'),('GR','grammar'),('GNG','negative_grammar'),('GE','pathology'),('GX','constitution')]:
            if identifier.startswith(prefix):return role
        return 'reference'
    if source=='strict':
        if identifier.startswith('C-'):return 'distinction'
        if re.fullmatch('E\\d{3}',identifier):return 'error_catalog'
        if re.fullmatch('Q\\d+',identifier):return 'quality'
        if re.fullmatch('M\\d+',identifier):return 'method'
        if re.fullmatch('D\\d+',identifier) and len(identifier)<=3:return 'direction_or_status_review_exact_context'
        if identifier.startswith(('UGC','CR')):return 'register_or_arbitration'
        if re.fullmatch('G\\d{2}',identifier):return 'strict_review'
        if re.fullmatch('(R|NG)\\d+',identifier):return 'principle_grammar'
        if re.fullmatch('(P\\d{3}|D\\d+-\\d{3})',identifier):return 'source_principle'
        if identifier.startswith(('КЛ','ДК','ТЕСТ','ДР','ВО','ЛВ','ВК','ДЕФ','СД','РС','ВЛ','ФО','ИНЖ')):return 'structural_or_domain_rule'
        return 'protocol_or_reference'
    return 'engineering_or_project_specialization'

def build_registry():
    old=load_json(ROOT/'data/source_contracts_v2_reference.json')
    entries={};sources=[]
    # Old keys remain aliases; old suggested routes are archive data only.
    for x in old['contracts']:
        sid=x.get('source') or x['key'].split(':')[0]
        identifier=x.get('source_identifier') or x['key'].split(':')[1]
        start=x.get('source_start_line',x.get('start_line'))
        end=x.get('source_end_line',x.get('end_line',start))
        key=f"{sid}:{identifier}:L{start}"
        owner='G' if sid=='generative' else 'S' if sid=='strict' else 'infrastructure'
        y={'key':key,'aliases':[x['key']] if x['key']!=key else [],'source':sid,'source_identifier':identifier,
           'source_sha256':x['source_sha256'],'start_line':start,'end_line':end,
           'exact_text':x['exact_text'],'role':role_for(sid,identifier),'owning_component':owner,
           'route':owner+'.SOURCE.'+identifier,'execution_status':'definition_available_not_executed',
           'legacy_route_for_audit_only':x.get('primary_procedure')}
        entries[key]=y
    for sid,filename in FILES.items():
        raw=(ROOT/'sources'/filename).read_bytes();sha=hashlib.sha256(raw).hexdigest();lines=raw.decode('utf-8').splitlines(keepends=True)
        sources.append({'key':sid,'path':'sources/'+filename,'sha256':sha,'bytes':len(raw),'lines':len(lines)})
        headings=[]
        for i,line in enumerate(lines):
            m=re.match(r'^(#{1,6})\s+(.+?)\s*$',line.rstrip('\r\n'))
            if m:headings.append((i,len(m.group(1)),m.group(2)))
        for i,line in enumerate(lines):
            plain=line.rstrip('\r\n');m=re.match(r'^\*\*('+PAT+r')\.\s',plain)
            head=re.match(r'^#{1,6}\s+(?:\d+\.\s+)?('+PAT+r')\.(?:\s|$)',plain)
            hit=m or head
            if not hit:continue
            identifier=hit.group(1);key=f'{sid}:{identifier}:L{i+1}'
            if head:
                level=len(plain)-len(plain.lstrip('#'));end=next((n for n,lev,t in headings if n>i and lev<=level),len(lines))
            else:
                end=i+1
                while end<len(lines) and lines[end].strip() and not lines[end].startswith('**'):end+=1
            parents=[(n,lev,t) for n,lev,t in headings if n<=i]
            parent=max((h for h in parents if h[1]<=3),default=(0,1,'Начало'),key=lambda h:h[0])
            pend=next((n for n,lev,t in headings if n>parent[0] and lev<=parent[1]),len(lines))
            role=role_for(sid,identifier);owner='G' if sid=='generative' else 'S' if sid=='strict' else 'infrastructure'
            metadata={'key':key,'source':sid,'source_identifier':identifier,'source_sha256':sha,
                'start_line':i+1,'end_line':end,'exact_text':''.join(lines[i:end]).rstrip('\r\n'),
                'parent_start_line':parent[0]+1,'parent_end_line':pend,'parent_title':parent[2],
                'role':role,'owning_component':owner,'route':owner+'.SOURCE.'+identifier,
                'execution_status':'definition_available_not_executed'}
            if key in entries:
                metadata['aliases']=entries[key].get('aliases',[])
                metadata['legacy_route_for_audit_only']=entries[key].get('legacy_route_for_audit_only')
            entries[key]=metadata
    # Legacy definitions not caught by the heading grammar still receive their
    # authoritative parent section; a missing parent never becomes fabricated text.
    for x in entries.values():
        if 'parent_start_line' in x:continue
        raw=(ROOT/'sources'/FILES[x['source']]).read_bytes();ls=raw.decode('utf-8').splitlines(keepends=True)
        start=x['start_line']-1
        heads=[(i,len(m.group(1)),m.group(2)) for i,line in enumerate(ls) if (m:=re.match(r'^(#{1,3})\s+(.+)',line))]
        parent=max((h for h in heads if h[0]<=start),default=(0,1,'Начало'),key=lambda h:h[0])
        end=next((i for i,level,title in heads if i>parent[0] and level<=parent[1]),len(ls))
        x.update(parent_start_line=parent[0]+1,parent_end_line=end,parent_title=parent[2])
    result={'version':'3.0','sources':sources,'entry_count':len(entries),'contracts':list(entries.values()),
            'rule':'Маршрут — точный исходный смысл; применение оформляется отдельно. Неизвестное семейство не исполняется по совпадению слова.'}
    (ROOT/'data/corpus_registry.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return result

def deep_copy(x):return json.loads(json.dumps(x,ensure_ascii=False))

class Corpus:
    def __init__(self):
        self.registry=static_contract(ROOT/'data/corpus_registry.json');self.entries={x['key']:x for x in self.registry['contracts']};self.aliases={alias:x['key'] for x in self.entries.values() for alias in x.get('aliases',[])}
        self.sources={x['key']:x for x in self.registry['sources']}
        self.sections={}
        for row in static_contract(ROOT/'data/source_sections.json')['sections']:
            self.sections[row['key']]={**row,'source_identifier':row['key'],'source_sha256':self.sources[row['source']]['sha256'],
                'parent_start_line':row['start_line'],'parent_end_line':row['end_line'],'parent_title':row['title'],
                'role':'source_section','exact_text':row['text'].rstrip('\r\n')}
        self.closure=static_contract(ROOT/'data/context_closure.json')
    def lookup(self,source,identifier):
        matches=[x for x in self.entries.values() if x.get('source',x['key'].split(':')[0])==source and x['source_identifier']==identifier]
        if not matches:raise ValueError('Исходный идентификатор отсутствует: '+identifier)
        return [deep_copy(x) for x in sorted(matches,key=lambda x:x.get('start_line',x.get('line',0)))]
    def exact(self,key):
        key=self.aliases.get(key,key);x=self.entries[key] if key in self.entries else self.sections[key];sid=x.get('source',key.split(':')[0]);meta=self.sources[sid]
        raw=(ROOT/meta['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=meta['sha256']:raise ValueError('Изменён исходный корпус')
        # Exact source definition plus entire parent context. No silent cross-reference repair.
        start=x['start_line'];end=x.get('end_line',start)
        lines=raw.decode('utf-8').splitlines(keepends=True)
        ps=x.get('parent_start_line',start);pe=x.get('parent_end_line',end)
        return {'entry':x,'definition':''.join(lines[start-1:end]),'parent_context':''.join(lines[ps-1:pe]),'source_digest':meta['sha256']}
    def operation_contract(self,key):
        x=self.exact(key);entry=x['entry'];role=entry['role'];owner=entry['owning_component']
        if role in ('quality','direction','generation_status','reference','protocol_or_reference','direction_or_status_review_exact_context'):
            product='ApplicabilityOrQualityRecord';effect='Не выдавать справку или качество за порождённый предметный результат'
        elif role=='generation':product='CandidateSet';effect='Создать различимые кандидаты либо обоснованный нулевой результат; не повышать истину'
        elif role=='generation_control':product='GenerationControlRecord';effect='Управлять указанной фазой или проверкой порождения, не выдумывать кандидатов ради отчёта'
        elif role=='generation_selection_or_handoff':product='SelectionOrHandoff';effect='Сохранить исходные идентичности, отводы и открытый остаток'
        elif owner=='S':product='BoundedReviewOrDerivation';effect='Проверить ровно указанное различение/основание; не выводить предметную истину из формы'
        else:product='ScopedSourceApplication';effect='Сохранить исходный слой и определить локальную специализацию до применения'
        return {'id':entry['route']+':L'+str(entry['start_line']),'version':'3.0','owning_component':owner,'source_key':entry['key'],
                'source_digest':x['source_digest'],'role':role,'operation_exact_source':x['definition'],'mandatory_context':x['parent_context'],
                'required_input':['task_and_C','versioned_target_or_seed','applicability_reason','available_material','budget'],
                'output_type':product,'postcondition':effect,'universal_constraint':'COMMON.md: не смешивать определение, исполнение, проверку и допуск',
                'semantic_executor':'AI-agent_or_domain_reviewer','programmatic_guarantee':'Точная адресация, тип и сохранение переданных границ; не автоматическое доказательство смысла'}

    def manifest(self,*,components,entry_keys=(),file_paths=()):
        comps=set(components)
        if not comps or not comps<=set('GSD'):raise ValueError('Неверный состав')
        selected=set(entry_keys)
        for component in comps:selected.update(self.closure['mandatory_sections'][component])
        pending=list(selected)
        while pending:
            selected_key=pending.pop();entry=self.exact(selected_key)['entry']
            lookup_key=entry['source']+':'+entry['source_identifier']
            for dep in self.closure['dependencies'].get(lookup_key,[]):
                sid,identifier=dep.split(':',1);matches=self.lookup(sid,identifier)
                if len(matches)!=1:raise ValueError('Неоднозначная обязательная ссылка требует явной адаптации: '+dep)
                exact_key=matches[0]['key']
                if exact_key not in selected:selected.add(exact_key);pending.append(exact_key)
        paths=['COMMON.md','data/context_closure.json','data/adaptations.json','data/instruction_file_roles.json']+[f'components/{c}_SYSTEM.md' for c in sorted(comps)]+list(file_paths)
        file_roles=static_contract(ROOT/'data/instruction_file_roles.json')['files']
        files=[];seen_paths=set()
        for rel in sorted(set(paths)):
            path=(ROOT/rel).resolve()
            if ROOT.resolve() not in path.parents or not path.is_file():raise ValueError('Недоступная обязательная часть '+rel)
            normalized=path.relative_to(ROOT.resolve()).as_posix()
            if normalized not in file_roles:
                raise ValueError('Файл не зарегистрирован как активная инструкция; используйте точный справочный элемент: '+normalized)
            required=set(file_roles[normalized])
            if not required<=comps:
                raise ValueError('Скрытая загрузка отсутствующего компонента через файл: '+normalized)
            if normalized in seen_paths:continue
            seen_paths.add(normalized)
            raw=path.read_bytes();files.append({'path':normalized,'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),
                'role':'active_instruction','required_components':sorted(required)})
        entries=[]
        for key in sorted(selected):
            x=self.exact(key);owner=x['entry']['owning_component']
            if owner in 'GSD' and owner not in comps:raise ValueError('Скрытая загрузка отсутствующего компонента')
            entries.append({'key':key,'source_sha256':x['source_digest'],'definition_sha256':hashlib.sha256(x['definition'].encode()).hexdigest(),
                            'parent_sha256':hashlib.sha256(x['parent_context'].encode()).hexdigest()})
        m={'version':'3.0','components':sorted(comps),'files':sorted(files,key=lambda x:x['path']),'entries':entries,'corpus_digest':digest(self.registry['sources']),
           'meaning':'Проверяется состав доставленного контекста, не факт понимания моделью'}
        m['digest']=digest(m);return m
    def assemble_context(self,manifest,*,byte_limit):
        """Материализовать реально передаваемый текст; предел байтов не выдаётся за токены."""
        if type(byte_limit) is not int or byte_limit<1:raise ValueError('Нужен положительный предел контекста')
        parts=[];loaded_files={};loaded_entries={};seen_parents=set()
        for entry in manifest['files']:
            p=(ROOT/entry['path']).resolve()
            if ROOT.resolve() not in p.parents:raise ValueError('Путь вне поставки')
            raw=p.read_bytes();loaded_files[entry['path']]=hashlib.sha256(raw).hexdigest()
            parts.append('\n<instruction_fragment path="'+entry['path']+'">\n'+raw.decode('utf-8')+'\n</instruction_fragment>\n')
        for entry in manifest['entries']:
            x=self.exact(entry['key']);a=hashlib.sha256(x['definition'].encode()).hexdigest();b=hashlib.sha256(x['parent_context'].encode()).hexdigest()
            loaded_entries[entry['key']]=(a,b)
            if b not in seen_parents:
                parts.append('\n<reference_context source="'+x['entry']['source']+'" role="source_not_authority">\n'+x['parent_context']+'\n</reference_context>\n');seen_parents.add(b)
        self.verify_manifest(manifest,loaded_files=loaded_files,loaded_entries=loaded_entries)
        text=''.join(parts);size=len(text.encode('utf-8'))
        if size>byte_limit:raise ValueError('Нормативное замыкание не помещается; разделите работу, не обрезайте обязательные правила')
        return {'manifest_digest':manifest['digest'],'text':text,'bytes':size,'loaded_files':loaded_files,'loaded_entries':loaded_entries,
                'semantic_adherence':'not_inferred_from_loading','instruction_priority':'bounded_by_actual_host_policy'}

    def verify_manifest(self,manifest,*,loaded_files,loaded_entries):
        body={k:v for k,v in manifest.items() if k!='digest'}
        if digest(body)!=manifest.get('digest'):raise ValueError('Подменён манифест')
        current=self.manifest(components=manifest['components'],entry_keys=[e['key'] for e in manifest['entries']],file_paths=[x['path'] for x in manifest['files']])
        if current!=manifest:raise ValueError('Манифест устарел')
        if loaded_files!={x['path']:x['sha256'] for x in manifest['files']}:raise ValueError('Загружена не вся обязательная инструкция')
        if loaded_entries!={x['key']:(x['definition_sha256'],x['parent_sha256']) for x in manifest['entries']}:raise ValueError('Потерян точный элемент или его контекст')
        return True
if __name__=='__main__':print(json.dumps({'entries':build_registry()['entry_count']},ensure_ascii=False))
