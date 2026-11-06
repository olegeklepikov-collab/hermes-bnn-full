## Полный каталог объявленных методов

- `list_workspaces`: read. Lists workspaces available to the connected account, ordered by most recent activity.
- `create_workspace`: write. Creates a new workspace and returns its title and workspace_id. Use the returned workspace_id with workspace-scoped tools. Requires a non-empty 'title'.
- `get_orientation`: read. Undermind helps you find, read, and organize scholarly papers. Its tools work with both the global scholarly literature and workspaces containing papers, PDFs, deep searches, Markdown files, and folders. If you have not called this tool in the current conversation, call it before using the other Undermind tools. It explains what the tools do, how they work together, what workspaces and cite keys are, and how to refer to papers, files, folders, and deep searches. The response also tells you which Undermind account is connected.
- `inspect_files`: read. Browse files and folders.  - paths=[] → Shallow listing of root - paths=['/analysis/'] → Shallow listing of folder - paths=['/analysis/my-research'] → Full file content
- `inspect_folders`: read. Browse the workspace's folders and their papers.  - folders=[] → the folder tree: each folder with its direct file, search, and paper counts - folders=['/literature/crispr-delivery/'] or ['crispr-delivery'] → that folder's direct contents: subfolders, files, searches, and papers
- `inspect_deep_searches`: read. Browse deep literature searches.  Searches live in the workspace folder tree. Listings show each search's folder path; address a search by bare name (when unique) or by full path (e.g. '/analysis/my-search') when the name repeats across folders.  - names=[] → All searches (folder path, status, timestamps) - names=['initial-search'] or ['/analysis/initial-search'] → Search details (goal, summary of results, timestamps, relevant papers) - names=['initial-search'], status_only=True → Just path + status and timestamps (fast, for polling) - names=['initial-search'], papers_only=True → Relevant papers list + search status, without goal or summary; use this for repeat/paginated reads
- `get_paper_info`: read. Look up detailed metadata for papers, and where they are located in the workspace.
- `display_references`: read. Shows papers that are important to the current discussion in an interactive reference card with bibliographic details and expandable abstracts. Use it when first discussing them. Display at most one card of any kind per turn.
- `display_deep_search_results`: read. Shows a deep search in an interactive card with its research goal and estimated progress while running, and its summary and ranked papers with relevance and expandable abstracts when complete. Use it after launching a deep search or when discussing one existing search. Display at most one card of any kind per turn; give an overview of several searches in prose.
- `suggest_pdf_uploads`: read. Shows an interactive card that asks the user to upload PDFs for up to 5 papers, with a reason and one upload link. Use it when papers important to the current discussion lack full text and reading them would materially improve the answer. Display at most one card of any kind per turn. Frame the suggestion positively: the current abstracts, metadata, and available PDFs may already support useful work, and the suggested full texts would strengthen it further.
- `get_deep_search_status`: read. Used by interactive deep-search cards to update their status. Do not call it directly; use inspect_deep_searches when you need to check a search's status.
- `get_paper_pdf_status`: read. Used by interactive paper cards to check whether PDFs are now available. Do not call it directly; use get_paper_info to check PDF availability.
- `get_pdf_download_links`: read. Get download links for PDFs uploaded to the workspace or open-access PDFs already retrieved by Undermind.
- `search_papers`: read. Search for papers by semantic similarity.  search_type chooses the source: global corpus, the 'library' pool of papers previously surfaced in the workspace, papers citing seed_papers, or papers referenced by seed_papers. sample_abstract is always used as the semantic query within that source. Without sort_override, results are ordered by semantic similarity. With sort_override, the tool first keeps a bounded set of semantically similar candidates, then orders that set by date/year or citations per year before pagination; it is not a metadata sort over the whole source.
- `find_papers_by_author`: read. Find or disambiguate academic papers by author. Returns cite keys grouped by likely author identity and confidence.
- `lookup_papers_by_metadata`: read. Look up specific papers from bibliographic information and return papers with cite keys.  Use this to look up cite keys for particular papers by title, DOI, or citation entry. Accepts at most 300 items.
- `launch_deep_search`: job. Launch a comprehensive review of the scholarly literature that runs asynchronously for several minutes. The tool returns immediately; use inspect_deep_searches with status_only=True for quick status checks. Ultimately produces a ranked list of papers and a summary, stored in the workspace. Only a few searches can run in parallel at once.
- `read_pdfs`: read. Send sub-agents to read full-text PDFs and answer questions, summarize, or retrieve information.  Each paper gets its own sub-agent that can see the entire PDF, including figures, tables, and equations. Multiple papers are read in parallel.
- `write_file`: write. Create or update a file.  - To update content: provide content (full replace) or content_edits (targeted)
- `delete_file`: write. Delete a file
- `move_files`: write. Move files to a different folder.
- `create_folder`: write. Create a new folder.
- `delete_folder`: write. Delete a folder. Folder must be empty.
- `move_folder`: write. Move and/or rename a folder.
- `add_papers_to_folder`: write. Add papers to a folder.
- `remove_papers_from_folder`: write. Remove papers from a folder.
- `star_papers`: write. Star papers.
- `unstar_papers`: write. Unstar papers.
- `move_deep_searches`: write. Move deep searches to a different folder.
- `delete_deep_search`: write. Delete a deep search.

## Методические процедуры BN

Полный исходный порядок и ограничения сохранены в [BN-procedures-reference.md](BN-procedures-reference.md). Используй их методический смысл через текущие типизированные методы; исторические команды не исполняются.
