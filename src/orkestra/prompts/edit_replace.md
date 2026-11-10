Output format: SEARCH/REPLACE blocks. Send only the places you change, never whole files.

For each change write:
- the file path on its own line,
- then a line <<<<<<< SEARCH,
- then the current lines, copied exactly from the file (whole lines, same indentation),
- then a line =======,
- then the new lines that replace them,
- then a line >>>>>>> REPLACE.

Example:

src/calc.py
<<<<<<< SEARCH
def add(a, b):
    return a - b
=======
def add(a, b):
    """Return the sum of a and b."""
    return a + b
>>>>>>> REPLACE

Rules for this format:
- SEARCH must match exactly one place in the file. Include enough lines around the change to make it unique, but keep it short.
- Lines outside the blocks stay as they are. Do not repeat unchanged code in REPLACE beyond what SEARCH covers.
- Use several blocks for several places, in the order they appear in the file.
- To add lines above an existing line (a comment, a docstring), SEARCH that one line and write the new lines followed by that same line in REPLACE. Every line from SEARCH appears in REPLACE exactly once, unless you mean to change or delete it.
- To create a new file, leave SEARCH empty and put the whole new file in REPLACE.
- To delete lines, leave REPLACE empty.
- You may change these files: {editable}
- {new_files}
{protected}
- After the blocks, write one short sentence: what you changed.
- If the task is impossible or too ambiguous to do correctly, answer only one line: CANNOT_DO: <short reason>
