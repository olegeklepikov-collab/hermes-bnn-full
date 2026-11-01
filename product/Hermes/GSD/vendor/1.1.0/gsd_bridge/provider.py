"""Явно настроенный внешний поставщик G; команда никогда не приходит от модели."""
from __future__ import annotations
import os
from pathlib import Path
import subprocess
import tempfile
import time
from .common import BridgeError, canonical, digest, load, read_json, MAX_JSON_BYTES

def generation_provider(modules, request: dict):
    path = os.environ.get('GSD_PROVIDER_CONFIG')
    if not path:
        return None, None
    config = load(Path(path).expanduser().resolve())
    allowed = {'argv', 'cwd', 'timeout_seconds', 'context_byte_limit', 'entry_keys', 'provider_id'}
    if not isinstance(config, dict) or set(config) - allowed:
        raise BridgeError('PROVIDER_CONFIG', 'Неверный договор настройки поставщика')
    argv = config.get('argv')
    if not isinstance(argv, list) or not argv or any(not isinstance(x, str) or not x for x in argv):
        raise BridgeError('PROVIDER_CONFIG', 'argv должен быть непустым списком строк')
    executable = Path(argv[0])
    if not executable.is_absolute() or not executable.is_file():
        raise BridgeError('PROVIDER_CONFIG', 'Нужен абсолютный путь исполняемого файла')
    timeout = config.get('timeout_seconds', 120)
    if type(timeout) not in (int, float) or not 0 < timeout <= 600:
        raise BridgeError('PROVIDER_CONFIG', 'Предел времени: от 0 до 600 секунд')
    from .context import ContextAssembler
    corpus = ContextAssembler(modules)
    manifest = corpus.manifest(components='G', entry_keys=config.get('entry_keys', []))
    context = corpus.assemble_context(manifest, byte_limit=config.get('context_byte_limit', 1500000))
    receipt = {'provider_id': config.get('provider_id', 'configured_command'),
               'request_digest': digest(request), 'context_manifest_digest': manifest['digest'],
               'process_invoked': False, 'semantic_acceptance': 'not_established'}

    def invoke(req):
        payload = {'contract': 'gsd.generation-provider/1', 'request': req,
                   'context': context, 'expected_output': {'candidates': 'list'}}
        # Файлы ограничивают потребление памяти; предел размера контролируется во время работы.
        with tempfile.TemporaryFile() as inp, tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            inp.write(canonical(payload)); inp.seek(0)
            proc = subprocess.Popen(argv, stdin=inp, stdout=out, stderr=err,
                                    cwd=config.get('cwd'), shell=False,
                                    env={**{k:v for k,v in os.environ.items() if k not in ('GSD_TRUST_KEY_FILE','GSD_HOST_POLICY','GSD_STATE_DIR')}, 'PYTHONUTF8': '1'})
            receipt['process_invoked'] = True
            start = time.monotonic()
            try:
                while proc.poll() is None:
                    if time.monotonic() - start > timeout:
                        raise BridgeError('PROVIDER_TIMEOUT', 'Поставщик не завершился в пределах срока')
                    if os.fstat(out.fileno()).st_size > MAX_JSON_BYTES or os.fstat(err.fileno()).st_size > MAX_JSON_BYTES:
                        raise BridgeError('PROVIDER_OUTPUT_LIMIT', 'Превышен предел вывода поставщика')
                    time.sleep(0.02)
                receipt['exit_code'] = proc.returncode
                if proc.returncode:
                    raise BridgeError('PROVIDER_FAILED', 'Поставщик завершился с ошибкой; stderr не раскрывается')
                out.seek(0)
                value = read_json(out.read(MAX_JSON_BYTES + 1))
                if not isinstance(value, dict) or set(value) != {'candidates'} or not isinstance(value['candidates'], list):
                    raise BridgeError('PROVIDER_OUTPUT', 'Ожидается объект с единственным полем candidates: list')
                receipt['output_digest'] = digest(value)
                return value['candidates']
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.wait()
    return invoke, receipt
