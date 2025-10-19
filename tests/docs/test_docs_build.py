"""文档构建测试

本测试用于验证 Sphinx 能够在本项目生成 HTML 文档，满足“3.2 API 文档生成”验收。
"""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.slow
def test_sphinx_build_html(tmp_path: Path) -> None:
    """构建 Sphinx HTML 文档并断言首页生成。

    参数：
        tmp_path (Path): Pytest 提供的临时目录，用于输出构建结果。

    断言：
        - `index.html` 存在，表示构建成功。
    """

    try:
        from sphinx.application import Sphinx
    except Exception as exc:  # pragma: no cover - 依赖环境异常
        pytest.skip(f"sphinx not available: {exc}")

    # 结构：repo_root/projects/sf-rdf-acl/tests/docs/test_docs_build.py
    # parents[4] 才是仓库根目录
    repo_root = Path(__file__).resolve().parents[4]
    docs_dir = repo_root / "projects" / "sf-rdf-acl" / "docs"
    assert docs_dir.is_dir(), f"docs dir not found: {docs_dir}"

    outdir = tmp_path / "_build"
    outdir.mkdir(parents=True, exist_ok=True)
    doctreedir = tmp_path / ".doctrees"
    doctreedir.mkdir(parents=True, exist_ok=True)

    app = Sphinx(
        srcdir=str(docs_dir),
        confdir=str(docs_dir),
        outdir=str(outdir),
        doctreedir=str(doctreedir),
        buildername="html",
    )
    app.build(force_all=True)

    index_html = outdir / "index.html"
    assert index_html.exists(), f"index.html not generated in {outdir}"
