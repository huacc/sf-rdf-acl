"""
Sphinx 配置文件。

本配置启用 autodoc、napoleon（Google 风格 docstring）、viewcode 以及 myst-parser 以支持 Markdown。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime


# 将项目 src 目录加入 Python 路径，便于 autodoc 直接导入包
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
PKG_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_ROOT = os.path.abspath(os.path.join(PROJECT_ROOT, "src"))
if SRC_ROOT not in sys.path:
    sys.path.insert(0, SRC_ROOT)


project = "SF-RDF-ACL"
author = "SemanticForge Team"
copyright = f"{datetime.now():%Y}"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",  # Google 风格 docstring
    "sphinx.ext.viewcode",
    "sphinx_autodoc_typehints",
    "myst_parser",  # 支持 .md 文档
]

autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
}

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_include_special_with_doc = True

templates_path = ["_templates"]
exclude_patterns: list[str] = []

html_theme = "furo"
html_static_path = ["_static"]

source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

master_doc = "index"

