from pathlib import Path
import json,sys
B=Path(__file__).resolve().parents[1];R=B.parent;D=R/'Dolt';sys.path.insert(0,str(D));from workspace_api import OPS;from scoped_mcp import BEADS,DOLT
workflows={
 'general-work':['Результат и критерии','Выполнение поручения','Проверка результата','Сохранение и передача итога'],
 'software-change':['Воспроизведение и границы изменения','Изменение кода или настройки','Проверка поведения и побочных эффектов','Передача результата и состояния'],
 'runtime-setup':['Требования и текущее состояние','Подготовка и настройка','Проверка запуска и взаимодействия','Рабочие инструкции и завершение'],
 'document-work':['Задание и исходные материалы','Создание или изменение документа','Проверка содержания и оформления','Сохранение и передача'],
 'exploratory-research':['Вопрос и границы','Поиск источников','Карта темы','Чтение выбранных источников','Сопоставление выводов','Проверка ссылок и ограничений','Сохранение результата и состояния'],
 'systematic-review':['Протокол и критерии','Поиск и журнал запросов','Объединение и проверка дублей','Отбор названий и аннотаций','Проверка доступных полных текстов','Извлечение и сопоставление данных','Независимая проверка исключений и выводов','Отчёт и сохранение версий'],
 'business-research':['Вопрос и единицы сравнения','Официальные и независимые источники','Извлечение сопоставимых наблюдений','Анализ различий и альтернатив','Проверка дат, единиц и обоснований','Отчёт, ограничения и версии данных'],
 'dataset-audit':['Происхождение и версия данных','Схема и единицы наблюдения','Пропуски и дубли','Сопоставление значений и связей','Исправления в отдельной ветке','Проверка изменений и показателей','Сохранение версии и исходных файлов'],
 'research-replication':['Вопрос и проверяемые результаты','Протокол воспроизведения','Исходные данные и ограничения доступа','Среда, версии и параметры','Выполнение расчётов','Проверка расхождений и устойчивости','Отчёт и воспроизводимая версия'],
 'research-handoff':['Перечень задач и артефактов','Проверка источников и уровня чтения','Текущее состояние и зависимости','Пробелы и следующие действия','Выгрузки и резервные копии','Проверка восстановления и передачи']}
formulas=B/'workspace/.beads/formulas';formulas.mkdir(exist_ok=True)
for name,steps in workflows.items():
 f={'formula':name,'description':'Рабочий процесс Hermes BN: {{question}}','version':1,'type':'workflow','vars':{'question':{'description':'Исследовательский вопрос','required':True}},'steps':[{'id':'step-'+str(i+1),'title':title+': {{question}}','description':'Результат должен быть проверяемым; сохранять источники, критерии, ограничения и артефакты. Шаг не считается выполненным только по факту запуска инструмента.','type':'task',**({'needs':['step-'+str(i)]} if i else {})} for i,title in enumerate(steps)]}
 (formulas/(name+'.formula.json')).write_text(json.dumps(f,ensure_ascii=False,indent=2))
(B/'config/workflows.json').write_text(json.dumps(workflows,ensure_ascii=False,indent=2))
profiles={n:{'server':'beads-dolt','method':'workflow_create','arguments':{'template':n},'required':['question']} for n in workflows}
for n in ['ready','blocked','stats','list']:
 profiles['tasks-'+n]={'server':'beads','method':n,'arguments':{}}
queries={
 'schema':"SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema='knowledgework' ORDER BY table_name,ordinal_position",
 'source-register':'SELECT dataset_id,source_sha256,row_count,imported_at FROM research_sources ORDER BY imported_at DESC',
 'dataset-counts':'SELECT dataset_id,COUNT(*) AS records FROM research_records GROUP BY dataset_id',
 'worktree-status':'SELECT * FROM dolt_status',
 'commit-history':'SELECT commit_hash,committer,date,message FROM dolt_log LIMIT 20',
 'branches':'SELECT * FROM dolt_branches',
 'table-history':'SELECT * FROM dolt_history_research_sources LIMIT 50',
 'source-hash-check':"SELECT dataset_id,CHAR_LENGTH(source_sha256) AS hash_length,row_count FROM research_sources",
 'asreview-label-counts':"SELECT JSON_UNQUOTE(JSON_EXTRACT(payload,'$.included')) AS imported_label,COUNT(*) AS records FROM research_records GROUP BY imported_label",
 'task-data-version':"SELECT DOLT_HASHOF('HEAD') AS version,ACTIVE_BRANCH() AS branch,DATABASE() AS database_name"}
for name,q in queries.items():
 profiles['sql-'+name]={'server':'dolt','method':'query','arguments':{'working_database':'knowledgework','working_branch':'main','query':q}}
for name in ['memory_list','beads_prime','beads_export','beads_backup','dolt_backup']:
 profiles[name]={'server':'beads-dolt','method':name,'arguments':{}}
for scope,allowed in [('beads',BEADS),('dolt',DOLT)]:
 raw=json.loads(((B if scope=='beads' else D)/'config/official-mcp-catalog.json').read_text());selected=[t for t in raw['tools']['tools'] if t['name'] in allowed]
 ((B if scope=='beads' else D)/'config/selected-mcp-tools.json').write_text(json.dumps(selected,ensure_ascii=False,indent=2))
for name,required in [('merge_preview',['source_branch','target_branch']),('merge_resolve',['source_branch','target_branch','resolutions','message'])]:
 profiles[name]={'server':'beads-dolt','method':name,'arguments':{},'required':required}
(D/'config/profiles.json').write_text(json.dumps(profiles,ensure_ascii=False,indent=2));(D/'config/workspace-tool-catalog.json').write_text(json.dumps({n:{k:v for k,v in v.items() if k!='fn'} for n,v in OPS.items()},ensure_ascii=False,indent=2));print('Selected official Beads:',len(BEADS),'official Dolt:',len(DOLT),'workspace:',len(OPS),'profiles:',len(profiles),'workflow templates:',len(workflows))
