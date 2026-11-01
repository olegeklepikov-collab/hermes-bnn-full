## Полный каталог объявленных методов

- `web_search`: read. Purpose: Perform web searches and return LLM-friendly results, including excerpts that are usually sufficient to answer directly without a follow-up fetch.  Ideal Use Cases: - Answering questions that require fresh or current information - Research, comparison, documentation, and troubleshooting questions - Broad tasks where multiple `search_queries` can be issued in a single call  For multiple independent objectives, make one web_search call per objective concurrently. Put related query variations for the same objective in a single call's search_queries list. 
- `web_fetch`: read. Purpose: Fetch and extract relevant content from specific web URLs. Use only when web_search excerpts are insufficient for the task at hand.  Ideal Use Cases: - The user asked about a specific URL or page - You need exact wording or quotes that excerpts may have truncated - You need full-page analysis (long article, document, or page structure) - web_search excerpts are conflicting or clearly insufficient to answer  For multiple independent extraction objectives, make separate web_fetch calls concurrently. Put related URLs that share one objective in a single call. 

## Методические процедуры BN

Полный исходный порядок и ограничения сохранены в [BN-procedures-reference.md](BN-procedures-reference.md). Используй их методический смысл через текущие типизированные методы; исторические команды не исполняются.
