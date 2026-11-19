"""``doctor`` warns when the installed tool runs a repository that is not on main
(düzeltme-fable a, D-104)."""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from orkestra import doctor, install
from orkestra.i18n import t

REPO = Path("/src/orkestra-repo")
TOOL_PREFIX = Path("/home/u/.local/share/uv/tools/orkestra-cli")


def test_an_editable_tool_on_a_feature_branch_warns() -> None:
    info = install.InstallInfo(source=REPO, prefix=TOOL_PREFIX, branch="faz-13x")
    check = doctor.install_check(info)
    assert check is not None and check.status == "warn"
    assert "faz-13x" in check.message
    assert check.message == t("doctor.install.branch", branch="faz-13x", path=REPO)


@pytest.mark.parametrize("branch", ["main", "master"])
def test_an_editable_tool_on_main_is_fine(branch: str) -> None:
    assert doctor.install_check(install.InstallInfo(REPO, TOOL_PREFIX, branch)) is None


def test_the_projects_own_environment_is_a_development_checkout_not_the_tool() -> None:
    info = install.InstallInfo(source=REPO, prefix=REPO / ".venv", branch="faz-13x")
    assert doctor.install_check(info) is None


def test_a_detached_head_warns_too() -> None:
    check = doctor.install_check(install.InstallInfo(REPO, TOOL_PREFIX, None))
    assert check is not None and check.data["branch"] is None


def test_a_normal_install_has_no_source() -> None:
    assert install.detect(read_direct_url=lambda: None) is None
    regular = '{"url": "https://files.example/x.whl", "archive_info": {}}'
    assert install.detect(read_direct_url=lambda: regular) is None
    assert install.detect(read_direct_url=lambda: "not json") is None


def test_detect_reads_the_branch_of_the_editable_source(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "faz-x"], cwd=repo, check=True)
    url = repo.as_uri()
    found = install.detect(
        read_direct_url=lambda: f'{{"url": "{url}", "dir_info": {{"editable": true}}}}',
        prefix=TOOL_PREFIX,
    )
    assert found == install.InstallInfo(repo, TOOL_PREFIX, "faz-x")


def test_doctor_shows_the_warning() -> None:
    info = install.InstallInfo(REPO, TOOL_PREFIX, "faz-13x")
    report = asyncio.run(doctor.run_doctor(install_info=lambda: info))
    assert [c.status for c in report.checks if c.name == "install"] == ["warn"]
    report = asyncio.run(doctor.run_doctor(install_info=lambda: None))
    assert not [c for c in report.checks if c.name == "install"]
