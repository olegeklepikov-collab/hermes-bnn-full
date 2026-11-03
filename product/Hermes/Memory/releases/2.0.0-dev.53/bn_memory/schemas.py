S={'type':'string'}
P={'type':'string','description':'Относительный путь от текущего проекта либо абсолютный путь внутри собственного зарегистрированного проекта. Список корней: memory_status.readable_projects. Чтение другого проекта не меняет область текущей задачи. Дочерний агент не расширяет доступ.'}
SCHEMAS={
 'memory_working':('Версионированные рабочие данные задачи Beads. bind связывает текущий сеанс с первичной задачей; sources возвращает ID собственных нативных входов для точных цитат; commit сохраняет целую карточку с expected_revision и request_id; read читает текущую/историческую редакцию. Источник каждого пункта — точный диапазон исходного ввода. Прежние пункты сохраняются; статусы resolved_candidate/superseded_candidate не являются принятой проверкой. Рабочие данные не дают разрешений.',{'action':{'enum':['bind','sources','commit','read','pending_actions']},'beads_id':S,'turn_id':S,'offset':{'type':'integer','minimum':0},'page_size':{'type':'integer','minimum':1,'maximum':20},'revision':{'type':'integer','minimum':1},'expected_revision':{'type':'integer','minimum':0},'request_id':S,'items':{'type':'array','items':{'type':'object'}}},['action']),
 'memory_recovery':('Восстановить данные собственного сеанса: status — текущая ссылка и число незавершённых действий; checkpoints — перечень; pending_actions — исходные ID и неизвестные эффекты; read_checkpoint — точные страницы сохранённого JSON. Читать offset/next_offset до конца нужного сообщения. Старые разрешения и режимы не возобновляются. Ссылка и фрагмент не означают прочтение всей истории или изображения.',{'action':{'enum':['status','checkpoints','pending_actions','read_checkpoint']},'checkpoint_id':S,'section':{'enum':['messages','state']},'message_index':{'type':'integer','minimum':0},'offset':{'type':'integer','minimum':0},'page_size':{'type':'integer','minimum':1,'maximum':20},'max_chars':{'type':'integer','minimum':1,'maximum':8192}},['action']),
 'document_partition':('Разбить неизменный корпус на адресные пакеты без отсечения единиц. Только родитель. Продолжай по next_offset. Каждый пакет — отдельный corpus_id для ограниченного G/S/D; общее покрытие оригинала складывается из фактических квитанций. Сохрани продукты пакетов и проверь межпакетные противоречия перед общим выводом.',{'corpus_id':S,'max_characters':{'type':'integer','minimum':1024,'maximum':262144},'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':100}},['corpus_id']),
 'document_catalogue':('Зафиксировать полный перечень файлов заданного корпуса и оригиналы, без ограничения числа файлов или страниц. Не означает чтение. Неподдержанные и защищённые файлы учитываются как пропуски. Только родитель. Повтор того же request_id использует тот же снимок.',{'path':P,'request_id':S,'scope':{'enum':['task','project','owner']},'required_phases':{'type':'array','items':{'enum':['read','plan','collect','analyse','verify','report','G','S','D']}}},['path','request_id']),
 'document_extract':('Выполнить конечный шаг изолированного извлечения. При extracting повторить тот же doc_id; только extracted означает окончание. Единицы источника: страницы PDF, структурные части DOCX, строки CSV/Excel/SQLite/Parquet, текстовые блоки JSON/XML/SQL. Извлечение не означает чтение моделью. Макросы и SQL-скрипты не исполняются.',{'doc_id':S,'retry_after_repair':{'type':'boolean'}},['doc_id']),
 'document_describe':('Адресный индекс единиц источника, без утверждения чтения его текста. Продолжай до has_more=false.',{'doc_id':S,'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':100}},['doc_id']),
 'document_read':('Прочитать точный фрагмент единицы корпуса. PDF с графикой доставляется также изображением через доверенный обработчик. Повторно читай next_offset до конца единицы. Получение инструмента и получение модели учитываются раздельно.',{'corpus_id':S,'doc_id':S,'unit':{'type':'integer','minimum':0},'phase':{'enum':['read','plan','collect','analyse','verify','report','G','S','D']},'offset':{'type':'integer','minimum':0},'max_chars':{'type':'integer','minimum':1,'maximum':65536}},['corpus_id','doc_id','unit']),
 'document_status':('Проверить полный состав корпуса, пропуски и подтверждённую доставку материала модели по фазам. Доставка не доказывает смысловое понимание или научную приёмку. Не называй полным чтением извлечение или одну страницу.',{'corpus_id':S,'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':100}},['corpus_id']),
 'knowledge_ingest':('Cognee: обработать одну разрешённую запись или файл в конечном диапазоне. Родительский Hermes исполняет модели настоящими листовыми агентами; первичный оригинал и хеш сохраняются. Источник и граф остаются unreviewed.',{'record_id':S,'revision':{'type':'integer'},'path':P,'scope':{'enum':['owner','project','task']},'content_type':{'enum':['text','code']},'request_id':S,'offset':{'type':'integer','minimum':0},'length':{'type':'integer','minimum':1,'maximum':20000},'source_url':S},['request_id']),
 'knowledge_query':('Cognee: адресный контекст фрагментов/графа, без генерации окончательного ответа. Все источники принадлежат текущим областям; выводы графа не являются научным принятием.',{'query':S,'mode':{'enum':['chunks','hybrid','graph','temporal','summaries']},'limit':{'type':'integer','minimum':1,'maximum':5}},['query']),
 'knowledge_manage':('Cognee: status/read_source/read_context/enrich/lesson/forget/reindex. Обогащение и выделение урока — конечные операции родителя; отчёт стадий отличает выполненное и пропущенное. Отзыв сохраняет первичный оригинал.',{'action':{'enum':['status','read_source','read_context','enrich','lesson','forget','reindex']},'scope':{'enum':['owner','project','task']},'doc_id':S,'record_id':S,'context_ref':S,'request_id':S,'offset':{'type':'integer','minimum':0}},['action']),
 'memory_record':('Сохранить целую запись с происхождением. Сведения остаются непроверенными; секреты запрещены. Области task/project/owner; дочерняя запись запрещена.',{'content':S,'source_ref':S,'kind':{'enum':['preference','decision','note','source','candidate']},'request_id':S,'scope':{'enum':['task','project','owner']},'concepts':{'type':'array','items':S},'id':S,'expected_revision':{'type':'integer','minimum':0}},['content','source_ref','kind','request_id']),
 'memory_recall':('Поиск по смыслу и словам во всех разрешённых областях Hermes BN; по умолчанию hybrid. Глобальное ранжирование объединяет память и допущенные фрагменты документов/UDR. records — записи памяти; source_fragments — точные фрагменты с происхождением; memory_read читает любой возвращённый ID. Это не полный охват корпуса и не зачёт чтения по фазам. local — словарный поиск записей и допущенных фрагментов источников без внешних служб. Для назначенного ребёнка hybrid использует только местный кэш вектора запроса и Zvec с предварительной фильтрацией; при отсутствии кэша возвращается словарный резерв, новый сетевой запрос не запускается.',{'query':S,'mode':{'enum':['local','hybrid']},'limit':{'type':'integer','minimum':1,'maximum':10},'offset':{'type':'integer','minimum':0}},['query']),
 'memory_read':('Повторное чтение записи MEM- или фрагмента SRC- в разрешённой области с проверкой первичного источника и хеша. Фрагмент не означает полный документ или зачёт фазы. Отозванные и изменённые источники недоступны.',{'id':S,'revision':{'type':'integer','minimum':1}},['id']),
 'memory_retract':('Отозвать свою запись с проверкой ожидаемой версии. История сохраняется; производные индексы получают удаление. Не удаляет прежнюю переписку.',{'id':S,'expected_revision':{'type':'integer','minimum':1}},['id','expected_revision']),
 'memory_sync':('Один ограниченный проход индексов. target=lexical обновляет только местные фрагменты без сети и эмбеддингов; отказы видны, повтор не рекурсивный.',{'target':{'enum':['lexical']},'limit':{'type':'integer','minimum':1,'maximum':10}},['target']),
 'memory_scope':('Переключить область родительского сеанса на проект, заранее зарегистрированный владельцем. Новые каталоги и дочерние переключения запрещены.',{'project':S},['project']),
 'memory_status':('Состояние общей памяти, текущая область и очередь индексов. Наличие настройки не доказывает работоспособность службы.',{},[]),
 'memory_files':('Читать страницу местного файла через Mirage в разрешённом проекте; вернуть хеш и уровень чтения. Секреты, внешние пути и запись запрещены.',{'action':{'enum':['read','ls']},'path':P,'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':8192}},['path']),
 'memory_code':('Serena: адресный обзор символов, исходный код символа или входящие ссылки в разрешённом проекте. Только чтение, без команд и редактирования.',{'action':{'enum':['overview','symbol','references']},'path':P,'symbol':S},['action','path']),
}

# Schema v2 attributes. Unknown fields remain rejected by the server's outer schema.
SCHEMAS['memory_read'][1].update(offset={'type':'integer','minimum':0},max_chars={'type':'integer','minimum':1,'maximum':4096})
_read=SCHEMAS['memory_read'];SCHEMAS['memory_read']=(_read[0]+' RCL-ID читает страницы сохранённого полного ответа поиска: offset/max_chars, до next_offset=null; хеши проверяются. MEM-/SRC-ID читают первичные данные как прежде. Файл spillover и read_file для этого не нужны.',_read[1],_read[2])
_recall=SCHEMAS['memory_recall'];SCHEMAS['memory_recall']=(_recall[0]+' Большой ответ возвращает record_refs/source_refs, сведения о поставщиках и RCL-ID. Полные исходные байты результата сохранены; читать RCL через memory_read(offset,max_chars), оригиналы через MEM-/SRC-ID. Ссылки сами по себе не являются чтением.',_recall[1],_recall[2])
SCHEMAS['memory_recovery'][1]['action']['enum'].append('action_status')
SCHEMAS['memory_recovery'][1]['nonce']=S
from bn_memory.record_metadata import HORIZONS, MEMORY_TYPES, ROLES
SCHEMAS['memory_library']=('Закреплённая личная библиотека Zotero BNN: поиск и карточки, существующие вложения и изолированный общий разбор. Метаданные не означают чтение статьи.',
 {'action':{'enum':['search','item','children','collections','attachment','parse','export']},'key':{'type':'string','pattern':'^[A-Z0-9]{8}$'},
  'query':{'type':'string','maxLength':1024},'limit':{'type':'integer','minimum':1,'maximum':100},'offset':{'type':'integer','minimum':0},
  'format':{'enum':['ris','bibtex','csljson']},'unit':{'type':'integer','minimum':0},'request_id':{'type':'string','minLength':1,'maxLength':128}},['action'])
SCHEMAS['memory_sync'][1]['target']['enum']=['lexical','projections']
SCHEMAS['memory_record'][1].update({
 'horizon': {'enum': list(HORIZONS)},
 'memory_type': {'enum': list(MEMORY_TYPES)},
 'event_time': {'type': ['string', 'null'], 'maxLength': 40},
 'valid_from': {'type': ['string', 'null'], 'maxLength': 40},
 'valid_to': {'type': ['string', 'null'], 'maxLength': 40},
 'classification_reason': {'type': 'string', 'minLength': 1, 'maxLength': 1024},
 'visibility': {'type': 'object', 'additionalProperties': False,
  'required': ['allowed_roles', 'evidence_use'],
  'properties': {'allowed_roles': {'type': 'array', 'minItems': 1, 'uniqueItems': True,
                                 'items': {'enum': list(ROLES)}},
                 'evidence_use': {'enum': ['unclassified', 'generation', 'verification', 'general']}}}
})

SCHEMAS['memory_record'][1]['source_dependencies'] = {
 'type':'array','maxItems':128,'uniqueItems':True,'items':{'oneOf':[
  {'type':'object','additionalProperties':False,'required':['kind','sha256'],
   'properties':{'kind':{'const':'source'},'sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'}}},
  {'type':'object','additionalProperties':False,'required':['kind','id','revision','content_hash'],
   'properties':{'kind':{'const':'record'},'id':{'type':'string','pattern':'^MEM-[a-f0-9]{24}$'},
                 'revision':{'type':'integer','minimum':1},'content_hash':{'type':'string','pattern':'^[a-f0-9]{64}$'}}}
 ]}}

SCHEMAS['memory_compute'] = ('Изолированное вычисление Python по явно переданным данным и разрешённым записям памяти. Без сети, ключей, настроек, чтения других файлов и файловых записей. INPUT содержит data и records. run выполняется один раз по request_id; status/read читают сохранённый результат. Только стандартная библиотека. Вывод остаётся непроверенными данными, не правами или научной приёмкой.',
 {'action':{'enum':['run','status','read']},'script':{'type':'string','minLength':1,'maxLength':65536},'data':{},
  'record_ids':{'type':'array','maxItems':128,'uniqueItems':True,'items':{'type':'string','pattern':'^MEM-[a-f0-9]{24}$'}},
  'request_id':{'type':'string','minLength':1,'maxLength':128},'job_id':{'type':'string','pattern':'^CMP-[a-f0-9]{32}$'},
  'stream':{'enum':['stdout','stderr']},'offset':{'type':'integer','minimum':0},'limit':{'type':'integer','minimum':1,'maximum':16384}},['action'])

SCHEMAS["knowledge_ingest"][1]["unit"]={"type":"integer","minimum":0}

SCHEMAS["memory_sync"][1]["target"]["enum"].append("reconcile")
SCHEMAS["memory_sync"][1].update(id={"type":"string","pattern":"^MEM-[a-f0-9]{24}$"},backend={"enum":["agentmemory","graphiti","zvec"]})

SCHEMAS["memory_data"]=("Прочитать страницу точной версии объекта Dolt по ссылке из первичной Beads-задачи. Без произвольного SQL, смены ветки и записи. Метаданные задачи не дают новых полномочий.",{"bead_id":{"type":"string","minLength":1,"maxLength":128},"link_key":{"type":"string","pattern":"^[A-Za-z0-9_]{1,64}$"},"offset":{"type":"integer","minimum":0},"limit":{"type":"integer","minimum":1,"maximum":8192}},["bead_id"])

SCHEMAS['memory_artifact']=('Создать новый Markdown/TXT через create(file_name,content,request_id) либо зарегистрировать готовый файл собственного проекта. create сохраняет отдельный файл без перезаписи и сети; крупный текст разбивай на полные части, не отсекай. register сохраняет неизменные байты и хеш без чтения в модель; status отделяет регистрацию, отправку и проверку байтов; send передаёт только закреплённому владельцу. Не зависит от UDR. Получение владельцем не объявляется по ответу API. При неизвестном исходе не отправляй повторно.',{'action':{'enum':['create','register','status','send']},'file_name':{'type':'string','minLength':1,'maxLength':128},'content':{'type':'string','minLength':1,'maxLength':262144},'path':P,'request_id':{'type':'string','minLength':1,'maxLength':128},'artifact_id':S,'expected_sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},'caption':{'type':'string','maxLength':600}},['action'])

SCHEMAS['work_status']=('Предметный статус текущей работы. advance сохраняет цель, подтверждённый результат, текущий содержательный шаг, следующий продукт и ограничения; read читает состояние; publish отправляет только новую редакцию владельцу. Не публикуй статус на каждый инструмент. finished требует сохранённого и подтверждённо отправленного файла, но не означает научную приёмку или получение владельцем.',{'action':{'enum':['advance','read','publish']},'request_id':{'type':'string','minLength':1,'maxLength':128},'expected_revision':{'type':'integer','minimum':0},'state':{'enum':['started','progressed','blocked','finished']},'goal':{'type':'string','minLength':1,'maxLength':600},'completed':{'type':'array','maxItems':5,'items':{'type':'string','minLength':1,'maxLength':600}},'current':{'type':'string','minLength':1,'maxLength':600},'next':{'type':'string','minLength':1,'maxLength':600},'blockers':{'type':'array','maxItems':5,'items':{'type':'string','minLength':1,'maxLength':600}},'artifact_id':S},['action'])

SCHEMAS['crossref_lookup']=('Официальные библиографические метаданные Crossref через существующий закреплённый клиент в отдельном публичном режиме. Ключ и почта не используются. Карточка не является чтением статьи или проверкой её выводов. Сборщику разрешён только назначенный точный запрос.',{'query':{'type':'string','minLength':1,'maxLength':512},'rows':{'type':'integer','minimum':1,'maximum':3}},['query'])

SCHEMAS['memory_recall'][1].update({
 'strategy':{'enum':['semantic','lexical','targeted','exact','example','snapshot','heuristic']},
 'need':{'type':'object','additionalProperties':False,'required':['purpose','expected_output','sufficiency','scope'],'properties':{
     **{k:{'type':'string','minLength':1,'maxLength':1200} for k in ['purpose','expected_output','sufficiency']},'scope':{'const':'current_authorized_scopes'}}},
 'example':{'type':'object','additionalProperties':False,'required':['object','goal','environment','features','unknowns'],'properties':{
     **{k:{'type':'string','minLength':1,'maxLength':1200} for k in ['object','goal','environment']},
     'features':{'type':'array','minItems':1,'maxItems':16,'items':{'type':'string','minLength':1,'maxLength':1024}},
     'unknowns':{'type':'array','maxItems':16,'items':{'type':'string','minLength':1,'maxLength':1024}}}},
 'versions':{'type':'array','minItems':1,'maxItems':256,'items':{'type':'object','additionalProperties':False,'required':['id','revision','content_hash'],
     'properties':{'id':{'type':'string','pattern':'^(MEM-[a-f0-9]{24}|SRC-[a-f0-9]{32})$'},'revision':{'type':'integer','minimum':1},'content_hash':{'type':'string','pattern':'^[a-f0-9]{64}$'}}}},
 'trace_id':{'type':'string','minLength':1,'maxLength':128},'step_reason':{'type':'string','minLength':1,'maxLength':1200}
})
_old=SCHEMAS['memory_recall']
SCHEMAS['memory_recall']=(_old[0]+' При явной strategy передай need: purpose, expected_output, sufficiency, scope=current_authorized_scopes. exact/точный MEM-/SRC-ID читается до эмбеддинга. snapshot требует явную карту versions(id,revision,content_hash), страницы до next_offset=null; пропуски видны, отозванное не восстанавливается. example требует объект, цель, среду, признаки и неизвестное; аналогия не доказывает применимость. heuristic требует trace_id/step_reason; одинаковый запрос без новых первичных данных или прав останавливается без сети. Пустой ввод не запускает сбор.',_old[1],_old[2])

from bn_memory.research_providers import schemas as provider_schemas
SCHEMAS.update(provider_schemas())

from bn_memory.service_engine import schemas as service_schemas
SCHEMAS.update(service_schemas())
