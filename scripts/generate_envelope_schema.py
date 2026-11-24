"""Generate the public JSON Schema for Orkestra's JSON result documents."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from orkestra.envelope import BatchEnvelope, BatchEstimate, ResultEnvelope


def main() -> None:
    """Write the schema from the Pydantic models used by the CLI."""
    project_root = Path(__file__).resolve().parents[1]
    schema = TypeAdapter(ResultEnvelope | BatchEnvelope | BatchEstimate).json_schema()
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "Orkestra JSON result document"
    schema["description"] = (
        "One of the JSON documents emitted by orkestra run, batch, or batch --estimate."
    )
    output = project_root / "schemas" / "envelope.schema.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


if __name__ == "__main__":
    main()
