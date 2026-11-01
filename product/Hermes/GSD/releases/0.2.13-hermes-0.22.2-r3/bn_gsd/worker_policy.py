"""Explicit read-only worker surface; effectful paths fail closed."""
READ_TOOLS={'mcp__context__document_read','mcp__context__document_status','mcp__context__document_describe','web_search','web_extract','tool_search','tool_describe','mcp__udr__udr_research','mcp__udr__udr_workspace','mcp__udr__udr_compare_rates'}
READ_OPERATIONS={
 'exa':['web_search_exa','web_search_advanced_exa','web_fetch_exa'],
 'tavily':['tavily_search','tavily_extract','tavily_map'],
 'keenable':['search_web_pages','fetch_page_content'],
 'parallel_search':['web_search'],
 'firecrawl':['firecrawl_search','firecrawl_scrape','firecrawl_map','firecrawl_research_search_papers','firecrawl_research_inspect_paper','firecrawl_research_related_papers','firecrawl_research_read_paper'],
 'consensus':['search'],
 'scite':['search_literature','citation_graph','read_fulltext','search_patents','search_clinical_trials','get_clinical_trial'],
 'undermind':['get_paper_info','search_papers','find_papers_by_author','lookup_papers_by_metadata','read_pdfs'],
 'alphaxiv':['discover_papers','get_paper_content','answer_pdf_queries'],
 'openalex':['search_works','get_work','resolve_references','list_citations','search_entities','get_entity'],
 'pubmed':['pubmed_search','pubmed_fetch','pubmed_summary','pmc_read','pmc_table','pmc_metadata'],
 'crossref':['works_search','work_get','bibliographic_match','work_references','work_relations']}
for server,operations in READ_OPERATIONS.items():READ_TOOLS.update('mcp__'+server+'__'+op for op in operations)
def worker_allows(name,args,read_paths=None):
 if not isinstance(args,dict):return False
 if name=='mcp__firecrawl__firecrawl_scrape' and args.get('actions'):return False
 if name=='tool_call':
  calls=args.get('calls');return isinstance(calls,list) and len(calls)==1 and worker_allows(calls[0].get('name'),calls[0].get('arguments',{}),read_paths)
 if name not in READ_TOOLS:return False
 if name=='mcp__udr__udr_workspace':
  return read_paths is None or args.get('request',{}).get('path') in read_paths
 if name=='mcp__udr__udr_research':
  request=args.get('request',{});return request.get('action')=='status' or (request.get('action')=='read' and (read_paths is None or request.get('path') in read_paths))
 return True
