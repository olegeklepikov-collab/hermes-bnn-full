## Полный каталог объявленных методов

- `service_status`: read. Check the pinned Zotero instance, paths, account binding, item count and saved write authorization.
- `schema`: read. Get the actual local schema, item fields, creator fields and item-specific field/type lists.
- `item_template`: read. Return an empty item structure using official field lists and cached public templates.
- `groups`: read. Read available group libraries; group writes are disabled.
- `query_items`: read. Search metadata or indexed full text (qmode=everything). Returns records, not matched full text. Supports collection, saved search, tags, item types, trash and pagination.
- `get_item`: read. Read one item, note, attachment or annotation and its local optimistic version.
- `item_children`: read. Read child notes, attachments and PDF annotations.
- `collections`: read. Read collections and their hierarchy.
- `tags`: read. Read/search library or collection tags.
- `saved_searches`: read. Read native saved search names and conditions; execute through query_items(search_key).
- `fulltext_versions`: read. Read locally indexed attachment keys and versions since a local version.
- `read_fulltext`: read. Read a bounded slice of the indexed attachment text; report actual coverage and unread remainder.
- `attachment_info`: read. Resolve a stored local attachment within this independent Zotero library; return hash and size.
- `read_pdf_pages`: blocked. Extract original text from specified one-based PDF pages, at most ten. Does not perform OCR.
- `render_pdf_page`: blocked. Render one original PDF page to PNG in Zotero/exports; inspect it for tables, figures and layout.
- `export_items`: write. Export references in 14 translator formats or CSL bibliography HTML. Uses official Zotero styles; does not verify scientific conclusions.
- `create_items`: write. Create bibliographic records using official item fields. Inspect all per-entry failed results. Use a write token for a known retry.
- `patch_item`: write. Patch selected fields using the last read local expected_version; array fields replace the whole array.
- `create_collections`: write. Create collections with name and optional parentCollection; memberships do not move attachment files.
- `patch_collection`: write. Rename or reparent a collection with an optimistic version.
- `create_saved_searches`: write. Create native saved searches with name and condition/operator/value objects.
- `patch_saved_search`: write. Update native saved search fields with an optimistic version.
- `create_note`: write. Create an HTML research note. State sources, pages actually read, evidence and limitations.
- `attach_file`: write. Import an authorized local file from Zotero/inbox or Hermes data/workspace as a stored child attachment. Three-phase upload, hash verification, no overwritten files.
- `create_annotation`: write. Create a native PDF highlight on a specified page with verified text and bottom-left PDF rectangle coordinates.
- `index_fulltext`: write. Index actual extracted PDF text locally for qmode=everything; machine indexing is not agent reading. Rejects PDFs without text and unsupported plain-text attachment writes.
- `trash_item`: write. Move an explicitly disposable or user-approved item to recoverable Zotero Trash. Requires the last read local version.
- `restore_item`: write. Restore a trashed item using the last read local version.

## Методические процедуры BN

Полный исходный порядок и ограничения сохранены в [BN-procedures-reference.md](BN-procedures-reference.md). Используй их методический смысл через текущие типизированные методы; исторические команды не исполняются.
