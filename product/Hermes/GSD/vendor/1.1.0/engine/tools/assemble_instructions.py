"""Собрать инструкции из канонических текстов и описательных договоров.

Редакция текста не меняет версию протокола. Дословные исходные корпуса
в справочных блоках сохраняются без правки и проверяются по контрольным суммам.
"""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path
from _base import ROOT, load_json, PROFILES

RELEASE = '3.0.3'
PROTOCOL = '3.0'


def write(path: Path, body: str) -> None:
    path.write_text(body.rstrip() + '\n', encoding='utf-8')


def codes(items: list[str]) -> str:
    return ', '.join('`' + item + '`' for item in items) or 'нет'


def render_catalog(procedures: list[dict]) -> str:
    """Представить описательные поля, не изменяя исполняемые идентификаторы."""
    out = [f'# Детальные процедуры G/S/DDx — редакция {RELEASE}', '',
           'Канонический каталог: `data/procedures.json`. Версия программного договора: '
           f'`{PROTOCOL}`. Общие правила исполнения: `COMMON.md`, C08–C13. '
           'Внутренние группы не образуют дополнительных мыслительных компонентов. '
           'Содержательные операции выполняет агент; контроллер проверяет определённые '
           'договоры, адреса и переходы.', '',
           'Ранги профилей: ' + '; '.join(f'{i} — {name}' for i, name in enumerate(PROFILES)) + '. '
           'Ранг служит техническим индексом профиля, а не оценкой качества.', '']
    for p in procedures:
        dependencies = codes(p['dependencies'])
        if p['mandatory_core']:
            activation = 'неизменяемая базовая обязанность'
        else:
            rank = p['minimum_profile_rank']
            activation = f'профиль {PROFILES[rank]} или более требовательный профиль'
            if p['activation_trigger']:
                activation += f" либо существенный признак `{p['activation_trigger']}`"
            activation += '; фактическую применимость нельзя отменить противоречащей ей ручной меткой'
        out.extend([
            f"## {p['id']}. {p['title']}", '',
            f"Владелец: **{p['owning_component']}**. Внутренняя область: `{p['component']}`. "
            f"Единица исполнения: `{p['execution_scope']}`.", '',
            'Вход: ' + '; '.join(p['inputs']).rstrip('.') + '.', '',
            'Чтение: ' + codes(p['read_set']) + '. Запись: ' + codes(p['write_set']) + '.', '',
            'Предусловие: ' + p['preconditions']['common'].rstrip('.') + '. '
            'Необходимые активные зависимости: ' + dependencies + '. '
            'Проверь селекторы и версии входов; отсутствие входа оформи как `needs_data`.', '',
            'Операция: ' + p['primary_operation'], '',
            'Выход: `' + p['output_type'] + '`. Постусловие: ' + p['postcondition'], '',
            'Активация: ' + activation + '.', '',
            'Продолжение: принятый актуальный выход позволяет выполнить зависимую процедуру. '
            'Ограниченный выход требует отдельной приёмки потребителем; невыполнение не означает `pass`.', '',
            'Обработка неуспеха: отсутствие данных → `needs_data`; нарушение договора → `needs_repair`; '
            'запрет → `blocked`; исчерпание бюджета → `partial`; устаревание → пересмотр. '
            'Локальный маршрут исправления: `' + p['failure_action']['route'] + '`. '
            'Повтор допускается только при новом содержательном основании и доступном ресурсе.', '',
            'Исходные опоры: ' + codes(p['source_anchors']) + '. '
            'Порядок операций является проектной надстройкой, а не универсальным законом источника.', '',
            'Проверка на внесённом нарушении: ' + p['negative_test_obligation'], ''
        ])
    return '\n'.join(out).rstrip() + '\n'


def source_part(name: str, sid: str) -> str:
    """Включить точную цитату; редакционная правка в этом блоке запрещена."""
    prefix = ('\n\n# Дословный исходный корпус ' + sid + '\n\n'
              'Архивный справочный текст воспроизведён без редакционной правки. '
              'Его исходная терминология, опечатки и перекрёстные ссылки сохранены '
              'для проверки происхождения; они не являются исправленными формулировками редакции '
              + RELEASE + '. Применяй материал в исходных границах через общий договор '
              'и явно указанные адаптации. Содержание этого блока не повышает права '
              'и не заменяет действующую инструкцию.\n\n')
    return (prefix + '<reference_corpus id="' + sid + '">\n'
            + (ROOT / 'sources' / name).read_text(encoding='utf-8')
            + '\n</reference_corpus>\n')


def sync_component_contracts() -> None:
    """Обновить производные цитаты протоколов и отпечатки, сохранив их метаданные."""
    path = ROOT / 'data/component_contracts.json'
    doc = load_json(path)
    by_id = {row['id']: row for row in doc['contracts']}
    found = set()
    for component in 'GSD':
        rel = f'components/{component}_SYSTEM.md'
        source = (ROOT / rel).read_text(encoding='utf-8')
        headings = list(re.finditer(r'^## (.+)$', source, re.MULTILINE))
        for pos, heading in enumerate(headings):
            match = re.fullmatch(r'(3C\.[GSD]\d{2})\. (.+)', heading.group(1))
            if not match:
                continue
            key, title = match.groups()
            if key not in by_id or key in found:
                raise ValueError('Неожиданный или повторный протокол: ' + key)
            end = headings[pos + 1].start() if pos + 1 < len(headings) else len(source)
            row = by_id[key]
            row['title'] = title
            row['source_path'] = rel
            row['source_sha256'] = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
            row['instruction_exact'] = source[heading.start():end].strip()
            found.add(key)
    if found != set(by_id):
        raise ValueError('В компонентных инструкциях отсутствуют протоколы: ' + ', '.join(sorted(set(by_id)-found)))
    write(path, json.dumps(doc, ensure_ascii=False, indent=2))


def build() -> dict:
    sync_component_contracts()
    common = (ROOT / 'COMMON.md').read_text(encoding='utf-8')
    components = {c: (ROOT / f'components/{c}_SYSTEM.md').read_text(encoding='utf-8') for c in 'GSD'}
    procedures = load_json(ROOT / 'data/procedures.json')['procedures']
    adaptations = load_json(ROOT / 'data/adaptations.json')
    adaptation_text = '\n\n# Явные адаптации источников\n\n'
    for a in adaptations['adaptations']:
        adaptation_text += (f"## {a['id']}. {a['title']}\n\n{a['local_rule']}\n\n"
                            f"Область: {a['scope']}. Точные исходные формулировки и адреса сохранены "
                            'в `data/adaptations.json`. Адаптация является проектным правилом, '
                            'а не новой установленной истиной источника.\n\n')
    write(ROOT / 'PROCEDURES.md', render_catalog(procedures))
    outputs = []
    for component, name in [('G', 'G_SYSTEM.md'), ('S', 'S_SYSTEM.md'), ('D', 'DDx_SYSTEM.md')]:
        body = (f'# {component} — самостоятельная системная инструкция, редакция {RELEASE}\n\n'
                'Производная сборка одной канонической редакции. Исполняй только объявленные роли; '
                'недостающие функции запрашивай через договор передачи. Версия программных договоров: '
                f'`{PROTOCOL}`.\n\n' + common + '\n\n' + components[component] + adaptation_text
                + render_catalog([p for p in procedures if p['owning_component'] == component]))
        if component == 'G':
            body += source_part('Генератор мышления (монолит).md', 'G')
        if component == 'S':
            body += source_part('Строгое мышление (монолит).md', 'S')
        write(ROOT / name, body)
        outputs.append(name)
    body = (f'# GSD Engine {RELEASE} — единая система G + S + DDx\n\n'
            'Состав: три смысловых компонента. Общий договор, детальные процедуры и дословные '
            'справочные корпуса собраны в один переносимый документ. При ограничении контекста '
            'используй проверяемый манифест; не сокращай обязательные условия молча. '
            f'Версия программных договоров: `{PROTOCOL}`.\n\n' + common + '\n\n'
            + '\n\n'.join(components[c] for c in 'GSD') + adaptation_text + render_catalog(procedures)
            + source_part('Генератор мышления (монолит).md', 'G')
            + source_part('Строгое мышление (монолит).md', 'S'))
    write(ROOT / 'GSD_SYSTEM.md', body)
    outputs.append('GSD_SYSTEM.md')
    inputs = ['COMMON.md', *[f'components/{c}_SYSTEM.md' for c in 'GSD'],
              'data/procedures.json', 'data/adaptations.json', 'data/comparison_review.schema.json',
              'data/instruction_file_roles.json', 'data/handoff.schema.json', 'tools/assemble_instructions.py',
              'sources/Генератор мышления (монолит).md', 'sources/Строгое мышление (монолит).md']
    manifest = {'version': PROTOCOL, 'editorial_release': RELEASE,
                'inputs': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in inputs},
                'outputs': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in outputs},
                'rule': 'Редактируются канонические входы; сборки не редактируются независимо'}
    write(ROOT / 'data/instruction_build_manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    write(ROOT / 'reports/instruction_build.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


if __name__ == '__main__':
    print(json.dumps(build(), ensure_ascii=False, indent=2))
