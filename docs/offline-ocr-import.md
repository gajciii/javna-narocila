# Offline OCR import

`import_ocr_results` imports the JSON sidecars produced by the standalone OCR collectors.
It does not enqueue pipeline jobs, rerun OCR, request embeddings, or call AI analysis.
Only `text_present` sidecars without saved pages may require native PDF text extraction.

```sh
python manage.py import_ocr_results /path/to/results --report /path/to/dry-run.json
python manage.py import_ocr_results /path/to/results --apply \
  --backup /path/to/documents-before.jsonl --report /path/to/import.json
```

The default is a dry run. Applying requires a new backup filename; the command never overwrites
an existing backup. Each changed document's original metadata and pages are written to the backup.

The importer checks the document ID, original storage reference and stored content digest. Files
with identical hashes share one index. Existing readable text is preserved; OCR fills missing or
blank pages. Existing index contents and vectors remain intact. Unchanged documents are skipped.
Errors, unreadable documents, changed sources and PDF parsing limits are reported, not silently
marked as fully read. Partial OCR retains its blank pages and records their count in
`Document.extraction.ocr_import`.

New contents use `ocr-local-v1` and immutable identities derived from both file and page hashes.
They participate in ordinary full-text passage searches. `embed_chunks` and `pending_counts`
exclude all `ocr-local-` versions. Ordinary reindexing prefers the imported OCR for the same file,
so later pipeline runs cannot discard it. Importing the same batch again is a no-op.

Install `ocr_policy.py` and the corresponding `document_index.py` / `embeddings.py` changes in
every web and pipeline worker before applying the import. Restart workers that still have old
Python modules loaded. These changes must be part of future deployments as well; copying code
into a running container alone does not update its image.

For the initial production import, sidecars are under `/root/ocr-only/results` on server-1.
The dry-run report, application report, source backups and pre-import document backup are kept
under `/root/ocr-import-release`. No database passwords or AI keys are copied out of containers.

## Explicit OCR embeddings

The import itself does not create embeddings. After explicit authorization for paid API usage,
run the separate scoped command:

```sh
python manage.py embed_ocr_vectors --status
python manage.py embed_ocr_vectors --report /path/to/ocr-embedding-progress.json
```

This selects only referenced `ocr-local-v1` passages with missing vectors. Existing vectors,
other extractor versions, tenders and past awards remain unchanged. A run fixes its upper chunk
ID at startup; `--through-pk` preserves that boundary across restarts. Progress is saved after
each batch. Repeating the command skips all vectors already saved. The ordinary pipeline's
automatic exclusion remains in place for future OCR imports.

`--workers 2` (up to 4) processes several batches concurrently. PostgreSQL row locks prevent
overlapping provider calls for the same passage. `--max-batches` applies across all workers.
