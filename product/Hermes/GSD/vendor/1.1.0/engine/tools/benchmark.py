"""Локальное сравнение на шести искусственных конечных случаях, не оценка LLM.
Простая программа получает те же кандидаты/наблюдения; слабый первый ответ
показывается отдельно и не используется для заявления превосходства над ней.
"""
from copy import deepcopy
from time import perf_counter_ns
import json,platform,sys
from _base import ROOT,load_json,digest
from triad import execute_components

def simple_compare(candidates,observations):
    return [c['id'] for c in candidates if not any(o['state']=='observed' and o['method_valid'] and not o['used_for_generation'] and o['key'] in c['expectations'] and c['expectations'][o['key']]!=o['value'] for o in observations)]

def observation(value,state='observed',identity='RAW',origin='independent_raw'):
    return {'id':identity,'key':'raw','value':value,'source_id':'synthetic/'+identity,'origin_group':origin,'state':state,'method_valid':True,'used_for_generation':False}

def run():
    base=load_json(ROOT/'examples/triad_request.json');cases=[]
    for name,obs,expected in [('measurement_only',[observation('same')],['K1']),('process_only',[observation('slow')],['K2']),
                             ('missing_raw',[observation('same','not_measured')],['K1','K2']),('no_raw',[],['K1','K2']),
                             ('conflicting_raw',[observation('same'),observation('slow',identity='RAW2',origin='independent_raw2')],[]),
                             ('dependent_copy',[observation('same'),observation('same',identity='COPY')],['K1'])]:
        q=deepcopy(base);q['observations']+=obs
        cases.append((name,q,expected))
    # Verify exact toy vocabulary against fixtures, not quietly adjust after result.
    for c in base['candidates']:
        if c['id']=='K2' and c['expectations'].get('raw')!='slow':
            raise ValueError('Изменился словарь искусственной модели; версионируйте эталон')
    rows=[]
    for name,q,expected in cases:
        measurements={}
        for method in ('first_candidate','simple_program','GSD'):
            start=perf_counter_ns()
            if method=='first_candidate':output=[q['candidates'][0]['id']];units=None
            elif method=='simple_program':output=simple_compare(q['candidates'],q['observations']);units=len(q['candidates'])*len(q['observations'])
            else:
                result=execute_components('GSD',q);output=result['outputs']['D']['compatible_in_model'];units=result['resource']['spent_local_units']
            elapsed=perf_counter_ns()-start
            measurements[method]={'compatible_set':output,'matches_predeclared_oracle':sorted(output)==sorted(expected),'elapsed_ns':elapsed,'declared_local_units':units}
        rows.append({'id':name,'input_digest':digest(q),'expected_set':expected,'measurements':measurements})
    methods={m:{'correct_sets':sum(r['measurements'][m]['matches_predeclared_oracle'] for r in rows),'case_count':len(rows),'total_elapsed_ns':sum(r['measurements'][m]['elapsed_ns'] for r in rows)} for m in ('first_candidate','simple_program','GSD')}
    report={'version':'3.0','data_kind':'synthetic','cases':rows,'methods':methods,'repetitions':1,
        'interpretation':'Простая предметная программа и GSD сравниваются по одному конечному оракулу. Равная правильность не доказывает равенство трассировки, ограничений и восстановления; больший контроль не доказывает экономической выгоды.',
        'limits':['Нет свободной генерации LLM','Нет клинических или производственных данных','Время одного локального прогона без доверительного интервала','Калибровка не применима: вероятности не вычисляются','Внешние вмешательства не выполнялись; их вред/полезность не измерены'],
        'environment':{'python':sys.version,'platform':platform.platform()}}
    (ROOT/'reports/finite_benchmark.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report
if __name__=='__main__':print(json.dumps(run()['methods'],ensure_ascii=False,indent=2))
