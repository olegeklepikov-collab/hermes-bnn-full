## Полный каталог объявленных методов

- `tavily_search`: read. Полный Tavily Search: general/news/finance, четыре глубины, даты, домены, язык, точные фразы, изображения, ответы и расход.
- `tavily_extract`: read. Tavily Extract: выбранные URL, basic/advanced, полный текст или отрывки, markdown/text, изображения и расход. Проверять failed_results.
- `tavily_map`: read. Tavily Map: карта URL с пределом, глубиной, путями, доменами и смысловыми инструкциями; не доказывает полноту сайта.
- `tavily_crawl`: read. Tavily Crawl: ограниченный корпус страниц, фильтры, basic/advanced и отрывки. Явно задавать limit и allow_external.
- `tavily_research`: job. Создать исследование Tavily mini/pro/auto со схемой, четырьмя стилями ссылок, длиной и согласованными файлами. Сохранить request_id; затем получать прежнее задание через tavily_get_research.
- `tavily_get_research`: read. Получить существующее исследование по request_id. completed/failed завершают ожидание; include_usage показывает расход.
- `tavily_research_stream`: job. Выполнить Research с потоком SSE. Сохраняет события в собственном профиле и возвращает содержание, источники и конечный статус. Файлы передаются только по согласованному составу.
- `tavily_usage`: read. Прочитать расход и предел собственного ключа/счёта. Не вызывать чаще десяти раз за десять минут.
- `tavily_logs`: read. Прочитать ограниченный журнал собственного ключа. Платная возможность; filter_by_api_key:true. Не отправляет отзывы и не меняет ключи.
- `api_search`: read. Search for data based on a query; POST /search
- `api_extract`: read. Retrieve raw web content from specified URLs; POST /extract
- `api_crawl`: read. Initiate a web crawl from a base URL; POST /crawl
- `api_map`: read. Initiate a web mapping from a base URL; POST /map
- `api_createResearch`: job. Initiate a research task; POST /research
- `api_getResearch`: read. Get research task status and results; GET /research/{request_id}
- `api_post__feedback`: blocked. Submit feedback on a search request or session; POST /feedback
- `api_getUsage`: read. Get API key and account usage details; GET /usage
- `api_post__logs`: read. Get usage logs for your API keys; POST /logs
- `api_post__org_usage`: read. Get organization usage across all API keys; POST /org-usage

## Методические процедуры BN

Полный исходный порядок и ограничения сохранены в [BN-procedures-reference.md](BN-procedures-reference.md). Используй их методический смысл через текущие типизированные методы; исторические команды не исполняются.
