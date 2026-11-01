"""Ordinary Hermes teams use a primary Beads work item, without a fake Research run."""
import json
class BaseWork:
    module='base'
    def __init__(self,host):self.host=host
    def load(self,sid,work_id):
        self.host.store.writable(sid)
        if self.host.working.binding(sid)!=work_id:raise PermissionError('current_primary_work_binding_required')
        card,_=self.host.working._card(sid);primary=json.loads(card['primary_ref'])
        from bn_memory.working_beads import lookup
        actual=lookup(self.host.config,primary['id'])
        return {'sid':sid,'state':'active' if actual['status'] in {'open','in_progress'} else actual['status']},{'bead':primary['id']}
    def require_work(self,sid,work_id):
        row,_=self.load(sid,work_id)
        if row['state']!='active':raise PermissionError('primary_work_not_active')
    def call(self,sid,turn,args):
        self.host.admission.ready(sid,turn)
        from bn_memory.teams import Team
        team=Team(self);work_id=self.host.working.binding(sid)
        if args['action']=='plan':return team.plan(sid,work_id,args)
        if args['action']=='run':return team.run(sid,turn,work_id,args.get('expected_revisions'))
        if args['action']=='status':return team.status(sid,work_id)
        if args['action']=='continue':return team.continue_task(sid,work_id,args)
        raise ValueError('work_team_action_invalid')
