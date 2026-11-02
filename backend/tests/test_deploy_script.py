"""deploy.sh runs on the server the KNOWBASE shares (CLAUDE.md §1): any Docker clean-up in it must
be limited to this compose project, never the whole daemon (ultra review 2026-11-02, finding 1)."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY = REPO_ROOT / "deploy.sh"
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"

# Commands that act on every project of the Docker daemon unless filtered.
_DAEMON_WIDE = re.compile(r"\bdocker\s+(?:image|container|network|volume|system|builder)\s+prune\b")


def _project_name() -> str:
    match = re.search(r"^name:\s*(\S+)\s*$", PROD_COMPOSE.read_text(), re.MULTILINE)
    assert match, "docker-compose.prod.yml must set a top-level project name"
    return match.group(1)


def _commands() -> list[str]:
    lines = []
    for raw in DEPLOY.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            lines.append(line)
    return lines


def test_deploy_script_still_prunes_images() -> None:
    """The clean-up step stays (dangling images of this project would otherwise pile up)."""
    assert any(re.search(r"\bdocker\s+image\s+prune\b", c) for c in _commands())


def test_every_prune_is_limited_to_this_compose_project() -> None:
    label = f"label=com.docker.compose.project={_project_name()}"
    prunes = [c for c in _commands() if _DAEMON_WIDE.search(c)]
    assert prunes
    for command in prunes:
        assert f"--filter {label}" in command or f'--filter "{label}"' in command, command


def test_deploy_script_never_prunes_volumes_or_the_whole_system() -> None:
    for command in _commands():
        assert not re.search(r"\bdocker\s+(?:volume|system)\s+prune\b", command), command
        assert "--volumes" not in command, command
