"""How big a local model this computer runs comfortably (Faz 13l, D-096).

``doctor`` shows one suggestion line when a local provider is configured, and warns about a
configured local model that looks larger than that. A suggestion only: nothing is blocked,
and the sizes are rough (a 4-bit quantised model needs about 0.6 GB per billion parameters,
plus room for the context and the rest of the system).

Memory: total RAM from psutil; GPU memory from ``nvidia-smi`` when it is installed (no shell).
Half the RAM is counted, or the GPU's memory when it is larger: a model larger than a small
GPU still runs, split between the GPU and the CPU (Ollama does that), so a 4 GB card does not
hide 64 GB of RAM (code review, D-097).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import psutil

from orkestra.i18n import t

if TYPE_CHECKING:
    from orkestra.config.schema import Config
    from orkestra.doctor import Check

GB = 1024**3
MIB = 1024**2
# (memory in GB below which, the largest model size that fits)
SIZES: tuple[tuple[float, float], ...] = ((6, 3), (10, 7), (20, 14), (40, 32))
LARGEST = 70.0
LIGHT = "1.5b-3b"  # summaries, search, output digests: small is enough and fast
# ``14b``, ``1.5b``, ``32B``; a mixture of experts ``8x22b`` counts all of them.
_SIZE = re.compile(r"(?<![\d.])(?:(\d+)x)?(\d+(?:\.\d+)?)b\b", re.IGNORECASE)
NVIDIA_TIMEOUT_S = 5

Run = Callable[[list[str]], "str | None"]
Which = Callable[[str], "str | None"]


@dataclass(frozen=True)
class Machine:
    ram: int | None  # bytes
    vram: int | None  # bytes, the largest GPU


def _run(args: list[str]) -> str | None:
    try:
        done = subprocess.run(args, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=NVIDIA_TIMEOUT_S, check=False)  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def gpu_memory(run: Run | None = None, which: Which = shutil.which) -> int | None:
    """The largest NVIDIA GPU's memory in bytes; None without ``nvidia-smi`` or an answer."""
    run = _run if run is None else run  # looked up at call time: tests replace ``_run``
    program = which("nvidia-smi")
    if program is None:
        return None
    output = run([program, "--query-gpu=memory.total", "--format=csv,noheader,nounits"])
    values = []
    for line in (output or "").splitlines():
        try:
            values.append(int(float(line.strip())))
        except ValueError:
            continue
    return max(values) * MIB if values else None


def detect(run: Run | None = None, which: Which = shutil.which) -> Machine:
    try:
        ram: int | None = int(psutil.virtual_memory().total)
    except (psutil.Error, OSError):
        ram = None
    return Machine(ram, gpu_memory(run, which))


def _usable_gb(machine: Machine) -> float | None:
    found = [x for x in (machine.vram, machine.ram / 2 if machine.ram else None) if x]
    return max(found) / GB if found else None


def largest_number(machine: Machine) -> float | None:
    usable = _usable_gb(machine)
    if usable is None:
        return None
    return next((size for below, size in SIZES if usable < below), LARGEST)


def largest_size(machine: Machine) -> str | None:
    """``7b``: the largest model size for code work on ``machine``."""
    number = largest_number(machine)
    return None if number is None else f"{number:g}b"


def size_of(model_id: str) -> float | None:
    """Billions of parameters in a model name (``qwen2.5-coder:14b`` → 14), if it says."""
    # The tag first, else the name (``hf.co/.../Qwen2.5-Coder-32B-Instruct-GGUF:Q4_K_M``).
    tag = model_id.rsplit(":", 1)[-1] if ":" in model_id else ""
    found = _SIZE.search(tag) or _SIZE.search(model_id)
    if found is None:
        return None
    experts = int(found[1]) if found[1] else 1
    return experts * float(found[2])


def checks(config: Config, machine: Machine) -> list[Check]:
    """One suggestion line, and a warning per local model larger than it."""
    from orkestra.doctor import Check

    largest = largest_number(machine)
    if largest is None:
        return []
    gpu = t("doctor.hardware.gpu", vram=f"{machine.vram / GB:.0f}") if machine.vram else ""
    ram = f"{machine.ram / GB:.0f}" if machine.ram is not None else "?"
    found = [Check("computer", "info",
                   t("doctor.hardware.suggest", ram=ram, gpu=gpu, light=LIGHT,
                     largest=f"{largest:g}b"),
                   {"ram": machine.ram, "vram": machine.vram, "light": LIGHT,
                    "largest": f"{largest:g}b"})]  # fmt: skip
    for name, provider in config.providers.items():
        if not provider.local or not provider.enabled:
            continue
        for model in getattr(provider, "models", []):
            size = size_of(model.id)
            if size is not None and size > largest:
                found.append(Check(f"provider:{name}", "warn",
                                   t("doctor.hardware.too_big", model=model.id, size=f"{size:g}",
                                     largest=f"{largest:g}b"),
                                   {"model": model.id, "size_b": size}))  # fmt: skip
    return found
