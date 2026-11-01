"""Историческая проверка редакции 3.0.1 не применяется к функциональной 3.0.2."""
import json
if __name__ == '__main__':
    print(json.dumps({'status':'not_applicable','historical_release':'3.0.1',
                      'reason':'В 3.0.2 намеренно изменены алгоритмы; старый критерий неизменности не применим.',
                      'current_check':'python tools/verify_remediation.py'},ensure_ascii=False))
    raise SystemExit(2)
