"""Explicit process-local compatibility adapter for pinned Serena R containers.

No vendor file modification and no lexical replacement for native references.
The language server still supplies every reference. Only an omitted single-line
R function container is recovered from its actual document-symbol range.
Not installed in Production by importing this operator source.
"""
from copy import copy

def singleline_function(symbols,line,column):
    candidates=[]
    if type(line)is not int or type(column)is not int:return None
    for symbol in symbols:
        r=symbol.get('range') or symbol.get('location',{}).get('range',{})
        a,b=r.get('start',{}),r.get('end',{})
        if (symbol.get('kind')==12 and a.get('line')==b.get('line')==line
            and type(a.get('character'))is int and type(b.get('character'))is int
            and a['character']<=column<b['character']):candidates.append((a['character'],-b['character'],symbol))
    if not candidates:return None
    return copy(max(candidates,key=lambda item:item[:2])[2])

def install():
    from solidlsp.language_servers.r_language_server import RLanguageServer
    original=RLanguageServer.request_containing_symbol
    if getattr(original,'bnn_r_singleline_compat',False):return
    def containing(self,relative_file_path,line,column=None,strict=False,include_body=False,body_factory=None):
        result=original(self,relative_file_path,line,column,strict,include_body,body_factory)
        if result is not None or strict or not relative_file_path.lower().endswith('.r'):return result
        candidate=singleline_function(self.request_document_symbols(relative_file_path).iter_symbols(),line,column)
        if candidate is None:return None
        # original() has already supplied/checked location metadata for this file.
        if not candidate.get('location',{}).get('relativePath')==relative_file_path:return None
        if include_body:candidate['body']=self.create_symbol_body(candidate,factory=body_factory)
        return candidate
    containing.bnn_r_singleline_compat=True
    RLanguageServer.request_containing_symbol=containing

if __name__=='__main__':
    install()
    from serena.cli import top_level
    top_level()
