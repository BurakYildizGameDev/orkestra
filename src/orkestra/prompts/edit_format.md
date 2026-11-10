Output format: a single JSON object and nothing else:
{"files": [{"path": "<relative path>", "content": "<the COMPLETE file after your change>"}], "note": "<one short sentence: what you changed>"}

Rules for this format:
- "content" is the whole file after your change, never a diff or a fragment.
- List only the files you change. Use the paths exactly as given in the context.
- You may change these files: {editable}
- {new_files}
{protected}
