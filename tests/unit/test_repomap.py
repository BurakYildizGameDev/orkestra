"""Unit tests for chief repomap (AST parsing, heuristics, cache, MAP.md format)."""

from __future__ import annotations

from pathlib import Path

from orkestra.chief import repomap


def test_python_ast_extracts_classes_and_functions_and_signatures() -> None:
    code = """\
def standalone_func(x: int, y: str = "hello") -> bool:
    '''A standalone function.'''
    return True

async def async_fetch(url: str):
    pass

class DataProcessor(BaseProcessor):
    def process(self, item: dict) -> None:
        pass

    @classmethod
    def factory(cls):
        pass
"""
    symbols = repomap.extract_python_symbols(code)
    # Check that standalone function is found
    assert any("standalone_func(x: int, y: str" in s for s in symbols)
    # Check async function is found
    assert any("async def async_fetch(url: str)" in s for s in symbols)
    # Check class and methods are found
    assert any("class DataProcessor(BaseProcessor)" in s for s in symbols)
    assert any("process(self, item: dict)" in s for s in symbols)


def test_non_python_heuristic_symbols() -> None:
    js_code = """\
export function calculateTax(amount) {
    return amount * 0.2;
}

export class OrderService {
    checkout() {}
}
"""
    symbols = repomap.extract_generic_symbols(js_code, "calculator.js")
    assert any("calculateTax" in s for s in symbols) or any("OrderService" in s for s in symbols)


def test_map_cache_storing_and_clearing(tmp_path: Path) -> None:
    cache_dir = tmp_path / ".orkestra" / "cache" / "map"
    file_bytes = b"print('hello world')\n"
    content_hash = repomap.hash_content(file_bytes)

    # Initially missing
    assert repomap.get_cached_summary(content_hash, cache_dir=cache_dir) is None

    # Save summary
    repomap.save_cached_summary(
        content_hash, "Prints a greeting.", "src/hello.py", cache_dir=cache_dir
    )
    assert repomap.get_cached_summary(content_hash, cache_dir=cache_dir) == "Prints a greeting."

    # Clear cache
    removed = repomap.clear_cache(tmp_path)
    assert removed == 1
    assert repomap.get_cached_summary(content_hash, cache_dir=cache_dir) is None


def test_render_map_markdown() -> None:
    files = [
        repomap.FileMap(
            path="src/util.py",
            summary="Utility helpers.",
            symbols=["def add(a, b)", "class Helper"],
        ),
        repomap.FileMap(
            path="tests/test_util.py",
            summary="Tests for helpers.",
            symbols=["def test_add()"],
        ),
    ]
    md = repomap.render_markdown(files)
    assert "# Project Map" in md
    assert "## src/" in md or "src/util.py" in md
    assert "Utility helpers." in md
    assert "def add(a, b)" in md
