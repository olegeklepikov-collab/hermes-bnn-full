"""Native read_file routing. A failed middleware cannot fall through to unsafe in-process conversion."""
from pathlib import Path
from contextvars import ContextVar
import json
SAFE_ROUTE=ContextVar('bn_safe_document_read',default=False)
def needs_route(args):
 from tools.read_extract import EXTRACTABLE_EXTENSIONS,ANYDOC_EXTENSIONS
 return Path(str(args.get('path',''))).suffix.lower() in EXTRACTABLE_EXTENSIONS|ANYDOC_EXTENSIONS

def execute(host,args,session_id,tool_call_id,identity):
 from hermes_cli.execution_control import authorize
 from bn_memory.store import canonical,sha
 from bn_memory.documents import FORMATS
 token=SAFE_ROUTE.set(True)
 try:
  context={k:v for k,v in identity.items() if k not in {'original_args','original_request','tool_name','args','next_call'}};context.update(session_id=session_id,tool_call_id=tool_call_id)
  authorize('tool',{'tool_name':'read_file','args':args},boundary='bn_document_read_adapter',**context)
  try:
   if host.store.binding(session_id)['readonly']:raise PermissionError('Child must read its assigned corpus through document_read')
   path=Path(args['path']);fmt=FORMATS.get(path.suffix.lower())
   if not fmt:raise ValueError('format_not_in_local_safe_parser: provide a supported format; unsafe/hosted fallback is disabled')
   root,target=host.store.safe_file(session_id,str(path))
   st=target.stat();request='native-read-'+sha(canonical([str(target),st.st_size,st.st_mtime_ns,st.st_ctime_ns]))[:24]
   docs=host.document_store();phase=host.document_role(session_id) or 'read'
   inventory=docs.catalogue(session_id,{'path':str(target),'request_id':request,'scope':'task','required_phases':[phase]})
   if inventory['files_total']!=1 or not inventory['sources']:raise ValueError('one_scoped_document_required')
   source=inventory['sources'][0];result={'status':'addressed_document_required','corpus_id':inventory['corpus_id'],'doc_id':source['id'],'source_status':source['status'],
    'reading_level':'metadata_only','model_read':False,'unsafe_native_extractor_invoked':False,'content':'',
    'next':'Use context.document_extract until extracted, then document_describe and document_read. Continue next_offset and required images; check document_status. No unsafe terminal/hosted conversion fallback.'}
  except Exception as e:result={'status':'blocked','code':type(e).__name__+':'+str(e)[:200],'unsafe_native_extractor_invoked':False,'model_read':False}
  output=canonical(result)
  authorize('tool_result',{'tool_name':'read_file','args':args,'result':output},boundary='bn_document_read_adapter',**context)
  return output
 finally:SAFE_ROUTE.reset(token)
