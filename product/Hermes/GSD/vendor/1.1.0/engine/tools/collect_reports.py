"""Свести фактически выполненные группы; не помечать отсутствующую группу успешной."""
import json
from _base import ROOT,PROFILES,load_json,digest

def collect():
    files=['core_verification_report.json']+['trace_'+p.replace(' ','_')+'.json' for p in PROFILES]
    parts=[load_json(ROOT/'reports'/f) for f in files]
    tests=[t for p in parts for t in p['tests']]
    if any(p['version']!='3.0' or p['failed_count'] for p in parts):raise ValueError('Есть непрошедшая или несовместимая группа')
    if len({t['name'] for t in tests})!=len(tests):raise ValueError('Дубли испытаний')
    report={'version':'3.0','date':'2026-09-12','test_count':len(tests),'passed_count':sum(t['passed'] for t in tests),'failed_count':sum(not t['passed'] for t in tests),
            'profile_property_combinations':parts[0]['profile_property_combinations'],'process_isolation':True,
            'groups':[{'path':'reports/'+name,'test_count':p['test_count'],'passed_count':p['passed_count'],'report_digest':digest(p)} for name,p in zip(files,parts)],
            'scope':'Программные договоры, конечные смысловые примеры, семь сочетаний и шесть искусственных циклов. Не валидация свободного поведения LLM или предметной безопасности.',
            'environment':parts[0]['environment'],'traces':[t for p in parts for t in p['traces']],'tests':tests}
    (ROOT/'reports/verification_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report
if __name__=='__main__':
    r=collect();print(json.dumps({k:r[k] for k in ('test_count','passed_count','failed_count','profile_property_combinations')},ensure_ascii=False))
