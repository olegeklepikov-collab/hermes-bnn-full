"""Модуль Hermes: исходное ядро работает в отдельном интерпретаторе."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
MAX_BYTES=24*1024*1024

def _json(value):
    return json.dumps(value,ensure_ascii=False,allow_nan=False)

def _settings():
    path=HERE/'connection.json'
    if not path.is_file():
        raise RuntimeError('Сначала создайте connection.json командой scripts/configure.py')
    value=json.loads(path.read_text(encoding='utf-8'))
    if set(value)-{'bundle_root','python','state_dir','key_file','provider_config','enforce_analysis_only','safe_read_tools'}:
        raise ValueError('Неизвестные настройки соединения')
    for key in ('bundle_root','python','state_dir','key_file'):
        if not isinstance(value.get(key),str) or not Path(value[key]).is_absolute():
            raise ValueError('Требуется абсолютный путь: '+key)
    if type(value.get('enforce_analysis_only',True)) is not bool:
        raise ValueError('enforce_analysis_only: требуется bool')
    if value.get('enforce_analysis_only',True) is not True:
        raise ValueError('Отключение аналитического допуска не поддержано этой поставкой; необходима отдельно принятая точка внешнего действия')
    safe=value.get('safe_read_tools',[])
    if not isinstance(safe,list) or any(not isinstance(x,str) for x in safe):
        raise ValueError('safe_read_tools: требуется список точных имён')
    return value

def register(ctx):
    schemas=json.loads((HERE/'schemas.json').read_text(encoding='utf-8'))
    names=frozenset(x['name'] for x in schemas)
    settings=_settings()
    root=Path(settings['bundle_root'])
    if not (root/'gsd.py').is_file() or not Path(settings['python']).is_file():
        raise RuntimeError('Исполняемая поставка GSD не найдена')

    def invoke(name,args):
        try:
            if not isinstance(args,dict):
                raise ValueError('Аргументы должны быть объектом JSON')
            body=_json(args)
            if len(body.encode('utf-8'))>MAX_BYTES:
                raise ValueError('Превышен предел входных данных')
            config=_settings()
            env={**os.environ,'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1',
                 'GSD_STATE_DIR':config['state_dir'],'GSD_TRUST_KEY_FILE':config['key_file']}
            # Не наследовать поставщика из постороннего профиля.
            env.pop('GSD_PROVIDER_CONFIG',None)
            env.pop('GSD_HOST_POLICY',None)
            if config.get('provider_config'):
                env['GSD_PROVIDER_CONFIG']=config['provider_config']
            result=subprocess.run([config['python'],'-I','-B',str(Path(config['bundle_root'])/'gsd.py'),
                'call',name,'--json','-'],input=body,text=True,encoding='utf-8',
                capture_output=True,timeout=180,cwd=config['state_dir'],env=env,shell=False)
            if len(result.stdout.encode('utf-8'))>MAX_BYTES:
                raise RuntimeError('Ответ превышает договорный предел; он не был обрезан')
            value=json.loads(result.stdout)
            if not isinstance(value,dict) or type(value.get('ok')) is not bool:
                raise RuntimeError('Некорректный ответ отдельного процесса')
            return _json(value)
        except Exception as exc:
            return _json({'ok':False,'error':{'code':'HERMES_BRIDGE_ERROR','message':str(exc)},
                          'external_effect_performed':False})

    for schema in schemas:
        name=schema['name']
        def handler(args, _name=name, **kwargs):
            return invoke(_name,args)
        ctx.register_tool(name=name,toolset='gsd_integration',schema=schema,handler=handler)

    def before_tool(tool_name,args,task_id=None,**kwargs):
        try:
            config=_settings()
            if not config.get('enforce_analysis_only',True):
                return None
            if tool_name in names or tool_name in ('skill_view','skills_list') or tool_name in config.get('safe_read_tools',[]):
                return None
            return {'action':'block','message':'Профиль GSD разрешает только анализ. Внешний инструмент не включён в доверенный список.'}
        except Exception:
            return {'action':'block','message':'Обязательная проверка GSD недоступна; вызов запрещён.'}

    def before_model(**kwargs):
        return {'context':
            'GSD подключён через исходный Engine 3.0.3. Для GSD-задачи сначала вызови gsd_status, '
            'затем gsd_intake и gsd_context для выбранного состава. При наличии случая используй '
            'gsd_case_get/gsd_case_next. external_request передавай доверенной среде, не подменяй отсутствующий компонент. '
            'Для инженерных операций gsd_context вызывай с profile=engineering. '
            'Исполни предметную операцию, сохрани адресный результат и '
            'фиксируй его через gsd_case_change, не подменяя результат отчётом о вызове. '
            'gsd_execute выполняет только предусмотренные конечные операции, а не все рассуждения. '
            'Контекст должен быть передан полностью: сокращённое отображение не закрывает обязательство. '
            'Число определений не означает их исполнение. Неизвестность, отводы и зависимости сохраняй. '
            'Завершение GSD не даёт полномочия на запись, отправку или выполнение внешней команды.'}

    ctx.register_hook('pre_tool_call',before_tool)
    ctx.register_hook('pre_llm_call',before_model)
    if hasattr(ctx,'register_skill'):
        for path in sorted((root/'skills').glob('*/SKILL.md')):
            ctx.register_skill(path.parent.name,path)
    if hasattr(ctx,'register_command'):
        def command(raw):
            value=raw.strip()
            if not value or value=='status':
                return invoke('gsd_status',{})
            if value.startswith('catalog '):
                return invoke('gsd_catalog',{'query':value[8:],'limit':20})
            return 'Команды: /gsd status; /gsd catalog <текст>. Для исполнения используйте инструменты gsd_*.'
        ctx.register_command('gsd',command,description='Состав GSD и поиск определений')
