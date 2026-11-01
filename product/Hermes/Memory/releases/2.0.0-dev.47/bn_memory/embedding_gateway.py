"""Ephemeral purpose-bound compatibility transport for actual installed SDK clients."""
import contextvars,json,secrets,threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer


class Gateway:
    def __init__(self,broker,sid,purpose,consumer):
        if purpose not in {'query','document'} or consumer not in {'graphiti','foundation','cognee','agentmemory'}:
            raise ValueError('explicit_embedding_consumer_and_purpose_required')
        self.broker=broker;self.sid=sid;self.purpose=purpose;self.consumer=consumer
        self.scope=contextvars.copy_context();self.token=secrets.token_urlsafe(32);self.receipts=[];self.closed=False
        broker.store.binding(sid)
    def embed(self,body):
        if self.closed:raise PermissionError('embedding_gateway_closed')
        if body.get('model')!='voyage-4-large' or body.get('dimensions',1024)!=1024 or body.get('output_dimension',1024)!=1024:
            raise ValueError('embedding_client_contract_mismatch')
        if body.get('input_type',self.purpose)!=self.purpose or body.get('truncation',False) is not False:
            raise ValueError('embedding_client_purpose_or_truncation_mismatch')
        if body.get('encoding_format','float') not in {'float','base64',None} or body.get('output_dtype','float')!='float':raise ValueError('embedding_client_dtype_mismatch')
        texts=body['input'];texts=[texts] if isinstance(texts,str) else texts
        binding=self.broker.store.binding(self.sid)
        if binding['readonly']:
            if self.purpose!='query':raise PermissionError('child_embedding_document_not_admitted')
            vectors=[self.broker.cached_query_embedding(text) for text in texts]
            result={'vectors':vectors,'receipt':{'provider_requests':0,'provider_reported_tokens':0,'purpose':'query','query_vector':'local_cache_only'}}
        else:result=self.broker.embedding_result(texts,self.purpose)
        receipt={**result['receipt'],'consumer':self.consumer};self.receipts.append(receipt)
        values=result['vectors']
        if body.get('encoding_format')=='base64':
            import base64,struct
            values=[base64.b64encode(struct.pack('<1024f',*vector)).decode('ascii') for vector in values]
        answer={'object':'list','model':'voyage-4-large','data':[{'object':'embedding','index':i,'embedding':v} for i,v in enumerate(values)],
                'bn_receipt':receipt}
        tokens=receipt.get('provider_reported_tokens')
        answer['usage']={'prompt_tokens':tokens,'total_tokens':tokens} if tokens is not None else None
        return answer
    def __enter__(self):
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def reply(self,status,value):
                data=json.dumps(value,allow_nan=False).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def do_POST(self):
                if owner.closed or not secrets.compare_digest(self.headers.get('Authorization',''),'Bearer '+owner.token):self.reply(403,{'error':{'message':'embedding_scope_required'}});return
                if self.path!='/v1/embeddings':self.reply(403,{'error':{'message':'embedding_only_endpoint'}});return
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=262144:raise ValueError('embedding_request_limit')
                    value=owner.scope.copy().run(owner.embed,json.loads(self.rfile.read(size)))
                    self.reply(200,value)
                except Exception as exc:self.reply(403,{'error':{'message':type(exc).__name__,'code':'embedding_contract_or_permission_rejected'}})
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.server.daemon_threads=True
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_port)+'/v1'
        return self
    def __exit__(self,*args):
        self.closed=True;self.server.shutdown();self.server.server_close();self.thread.join(timeout=3)
