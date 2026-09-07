"""Keep MkDocs repository links on the revision used to build the docs.

Use relative Markdown links for files outside docs/ so the same sources also
work when read on GitHub. The hook validates those targets before turning them
into commit-specific GitHub links. It requires no additional MkDocs plugin.
"""

from pathlib import Path
import os
import re
import subprocess
import tomllib
from urllib.parse import quote, unquote, urlsplit, urlunsplit


REPO_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_LINK = re.compile(r"\]\((\.\./[^\s)]+)\)")


def on_config(config):
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())["project"]
    config["site_name"] = f"CAMAT {project['version']}"
    ref = os.environ.get("CAMAT_DOCS_REF")
    if not ref:
        try:
            ref = subprocess.check_output(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=REPO_ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ValueError(
                "Build docs from a Git checkout, or set CAMAT_DOCS_REF to the "
                "branch, tag or commit containing these sources."
            ) from exc
    config["extra"]["camat_repo_ref"] = ref
    config["edit_uri"] = f"blob/{quote(ref, safe='/')}/docs/"
    return config


def on_page_markdown(markdown, *, page, config, files):
    docs_dir = Path(config["docs_dir"]).resolve()
    source = Path(page.file.abs_src_path)

    def repository_url(match):
        url = urlsplit(match.group(1))
        target = (source.parent / unquote(url.path)).resolve()
        if target.is_relative_to(docs_dir):
            return match.group(0)  # MkDocs handles normal documentation links.
        if not target.is_relative_to(REPO_ROOT) or not target.exists():
            raise ValueError(f"{source}: missing repository link target {url.path!r}")
        kind = "tree" if target.is_dir() else "blob"
        ref = quote(config["extra"]["camat_repo_ref"], safe="/")
        path = quote(target.relative_to(REPO_ROOT).as_posix(), safe="/")
        destination = f"{config['repo_url'].rstrip('/')}/{kind}/{ref}/{path}"
        destination = urlsplit(destination)
        return "](" + urlunsplit(destination._replace(query=url.query, fragment=url.fragment)) + ")"

    return REPOSITORY_LINK.sub(repository_url, markdown)
