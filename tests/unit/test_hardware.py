"""Faz 13l: ``doctor`` suggests model sizes for this computer (a suggestion only, D-096)."""

from __future__ import annotations

import pytest

from orkestra import hardware
from orkestra.config.schema import Config

GB = 1024**3


@pytest.mark.parametrize(
    ("ram_gb", "vram_gb", "heavy"),
    [(4, None, "3b"), (8, None, "3b"), (16, None, "7b"), (32, None, "14b"), (64, None, "32b"),
     (16, 8, "7b"), (16, 12, "14b"), (32, 24, "32b"), (128, 48, "70b"),
     (64, 4, "32b")],  # a small GPU does not hide plenty of RAM (code review #35)
)  # fmt: skip
def test_the_largest_code_model_follows_the_memory(
    ram_gb: int, vram_gb: int | None, heavy: str
) -> None:
    machine = hardware.Machine(ram_gb * GB, vram_gb * GB if vram_gb else None)
    assert hardware.largest_size(machine) == heavy


def test_model_sizes_are_read_from_their_names() -> None:
    assert hardware.size_of("qwen2.5-coder:14b") == 14
    assert hardware.size_of("qwen2.5:1.5b-instruct-q4") == 1.5
    assert hardware.size_of("llama3.1:8b") == 8
    assert hardware.size_of("mistral") is None
    # Code review #35: Hugging Face ids keep the size in the name, MoE names multiply.
    assert hardware.size_of("hf.co/bartowski/Qwen2.5-Coder-32B-Instruct-GGUF:Q4_K_M") == 32
    assert hardware.size_of("mixtral:8x22b") == 176


def test_nvidia_memory_is_read_without_a_shell() -> None:
    calls: list[list[str]] = []

    def run(args: list[str]) -> str | None:
        calls.append(args)
        return "8192\n4096\n"

    assert hardware.gpu_memory(run, which=lambda name: "/bin/nvidia-smi") == 8192 * 1024**2
    assert calls[0][0] == "/bin/nvidia-smi"


def test_no_nvidia_tool_means_no_gpu_figure() -> None:
    assert hardware.gpu_memory(lambda args: "1", which=lambda name: None) is None
    assert hardware.gpu_memory(lambda args: "garbage", which=lambda name: "x") is None


def _config(*models: str) -> Config:
    return Config.model_validate({"version": 1, "providers": {
        "ollama": {"type": "ollama", "models": [{"id": m, "tier": 1} for m in models]},
        "api": {"type": "openai_compat", "base_url": "https://a.test/v1",
                "models": [{"id": "huge:405b", "tier": 3}]},
    }})  # fmt: skip


def test_doctor_suggests_sizes_and_names_local_models_too_big() -> None:
    machine = hardware.Machine(16 * GB, None)
    checks = hardware.checks(_config("qwen2.5:1.5b", "qwen2.5-coder:32b"), machine)

    [info] = [c for c in checks if c.status == "info"]
    assert "16 GB" in info.message and "7b" in info.message
    assert info.data["largest"] == "7b"
    [warn] = [c for c in checks if c.status == "warn"]
    assert "qwen2.5-coder:32b" in warn.message  # a remote model of any size is fine
    assert warn.name == "provider:ollama"


def test_unknown_memory_gives_no_suggestion() -> None:
    assert hardware.checks(_config("x:70b"), hardware.Machine(None, None)) == []
