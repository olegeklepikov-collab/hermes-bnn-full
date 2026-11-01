## Полный каталог объявленных методов

- `WolframContext`: read. Uses semantic search to retrieve any relevant information from Wolfram. Always use this tool at the start of new conversations or if the topic changes to ensure you have up-to-date relevant information. This uses semantic search, so the context argument should be written in natural language (not a search query) and contain as much detail as possible (up to 250 words).
- `WolframLanguageEvaluator`: read. Evaluates Wolfram Language code for the user in a Wolfram Language kernel. If a formatted result is provided as a markdown link, use that in your response instead of typing out the output. Parse natural language input with `\[FreeformPrompt]["query"]`, which is analogous to ctrl+= input in notebooks. Natural language input is parsed before evaluation, so it works like macro expansion. You should ALWAYS use this natural language input to obtain things like `Quantity`, `DateObject`, `Entity`, etc. This is a stateless kernel, so you cannot reuse definitions from previous evaluations.
- `WolframAlpha`: read. Use natural language queries with Wolfram|Alpha to get up-to-date computational results about entities in chemistry, physics, geography, history, art, astronomy, and more.

## Методические процедуры BN

Полный исходный порядок и ограничения сохранены в [BN-procedures-reference.md](BN-procedures-reference.md). Используй их методический смысл через текущие типизированные методы; исторические команды не исполняются.
