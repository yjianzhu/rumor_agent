from pathlib import Path

from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from markupsafe import Markup

from src.db.base import get_db

get_db_session = get_db

TEMPLATES_DIR = Path(__file__).parent / "templates"


# CommonMark + GFM-ish: 自动链接 + 删除线 + 表格。html=False 禁止 raw HTML，
# linkify 让裸 URL 变可点击；这一层已足以挡住 XSS 的常见路径，无需 bleach。
_md = MarkdownIt("commonmark", {"html": False, "linkify": True, "breaks": True}).enable(
    ["table", "strikethrough", "linkify"]
)


def render_markdown(text: str | None) -> Markup:
    if not text:
        return Markup("")
    return Markup(_md.render(text))


def make_templates() -> Jinja2Templates:
    """Return a Jinja2Templates instance with shared filters registered."""
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["markdown"] = render_markdown
    return templates


# View modes for the rumor listing.
# Maps view name → is_published filter (None = no filter).
VIEW_TO_PUBLISHED: dict[str, bool | None] = {
    "pending": False,
    "published": True,
    "all": None,
}


def resolve_view(view: str) -> tuple[str, bool | None]:
    """Normalize view name and return (canonical_view, is_published filter)."""
    if view not in VIEW_TO_PUBLISHED:
        view = "pending"
    return view, VIEW_TO_PUBLISHED[view]
