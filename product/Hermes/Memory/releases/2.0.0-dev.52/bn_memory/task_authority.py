"""One native Beads graph. The host stores only effect receipts, never a competing plan."""
import json,subprocess
from bn_memory.store import canonical,sha
class Tasks:
    def __init__(self,host,module='base'):self.host,self.module=host,module
    def run(self,args):
        from bn_memory.working_beads import lookup
        settings=self.host.config['working_beads']
        # The read validates the exact wrapper/environment/binary pins before any write.
        lookup(self.host.config,self.host.config['task_pin_probe'])
        value=subprocess.run([settings['command'],*args,'--json'],capture_output=True,text=True,timeout=45)
        if value.returncode:raise RuntimeError('Beads_operation_failed_outcome_requires_observation')
        return json.loads(value.stdout)
    def effect(self,sid,key,arguments,perform):
        if self.module=='research':self.host.modules.require(sid,'research')
        identifier='BEAD-'+sha(canonical([self.host.store.profile,sid,key]))[:24];fingerprint=sha(canonical(arguments))
        with self.host.store.db() as db:
            db.execute('BEGIN IMMEDIATE');old=db.execute('SELECT * FROM module_attempts WHERE profile_id=? AND id=?',(self.host.store.profile,identifier)).fetchone()
            if old:
                if old['input_hash']!=fingerprint:raise ValueError('Beads_operation_key_conflict')
                if old['state']!='succeeded':raise PermissionError('Beads_previous_outcome_requires_observation')
                return json.loads(old['body'])
            db.execute('INSERT INTO module_attempts VALUES(?,?,?,?,?,?,?,?)',(self.host.store.profile,sid,identifier,self.module,'',fingerprint,'running','{}'))
        try:value=perform()
        except BaseException:
            with self.host.store.db() as db:db.execute("UPDATE module_attempts SET state='unknown' WHERE profile_id=? AND id=?",(self.host.store.profile,identifier))
            raise
        with self.host.store.db() as db:db.execute("UPDATE module_attempts SET state='succeeded',body=? WHERE profile_id=? AND id=?",(canonical(value),self.host.store.profile,identifier))
        return value
    def get(self,request):
        rows=self.run(['show',request['issue_id']]);return {'status':'found','issue':rows[0]}
    def create(self,sid,title,goal,key,parent=None):
        args=['create','--title',title,'--description',goal,'--type','task']
        if parent:args+=['--parent',parent]
        return self.effect(sid,key,args,lambda:self.run(args))
    def claim(self,sid,bead,holder,key):return self.effect(sid,key,[bead,holder],lambda:self.run(['update',bead,'--assignee',holder,'--status','in_progress']))
    def close_owned(self,sid,bead,holder,key,reason):
        current=self.get({'issue_id':bead})['issue']
        if current['status']=='closed':return {'status':'closed','id':bead,'observed_existing':True}
        if current.get('assignee')!=holder:raise PermissionError('native_task_holder_changed')
        args=['--actor',holder,'close',bead,'--reason',reason]
        return self.effect(sid,key+':owned-holder',[bead,holder,reason],lambda:self.run(args))

    def plan(self,sid,args):
        self.host.store.writable(sid);items=args['tasks'];keys=[t['key'] for t in items]
        if not 1<=len(items)<=32 or len(keys)!=len(set(keys)):raise ValueError('split_plan_or_duplicate_task_keys')
        pending={t['key']:set(t.get('depends_on',[])) for t in items};done=set()
        while pending:
            ready=[k for k,deps in pending.items() if deps<=done]
            if not ready:raise ValueError('task_cycle_or_missing_dependency')
            for k in ready:done.add(k);pending.pop(k)
        parent=args.get('parent_bead');result={}
        if parent:self.get({'issue_id':parent})
        for task in items:
            row=self.create(sid,task['title'],task['goal'],args['request_id']+':'+task['key'],parent);result[task['key']]=row['id']
        for task in items:
            for predecessor in task.get('depends_on',[]):
                edge=[result[task['key']],result[predecessor]]
                self.effect(sid,'edge:'+':'.join(edge),edge,lambda e=edge:self.run(['dep','add',e[0],e[1],'--type','blocks']))
        return {'primary':'Beads','tasks':result,'competing_graph_created':False,'hierarchy_is_primary_parent_links':True}
