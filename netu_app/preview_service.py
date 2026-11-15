"""判断文件可用哪种方式在线预览，并把文本 / 表格 / Office 内容渲染成安全 HTML。

全部使用 Python 标准库实现，不依赖外部服务或第三方 JS，保证离线与隐私场景可用。
"""

import csv
import io
import json
import re
import zipfile
from datetime import datetime
from html import escape as html_escape
from pathlib import Path
from xml.etree import ElementTree

WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
DRAWING_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_TABLE_ROWS = 500
MAX_TABLE_COLS = 60
MAX_OFFICE_ROWS = 300
MAX_OFFICE_COLS = 40
MAX_SLIDES = 120
MAX_DOCX_PARAGRAPHS = 3000


class PreviewService:
    """把文件的扩展名映射到一种预览方式，并负责把文本内容渲染成 HTML。"""

    IMAGE_EXTS = {
        ".jpg", ".jpeg", ".jfif", ".pjpeg", ".png", ".gif", ".webp", ".svg",
        ".bmp", ".ico", ".avif", ".apng",
    }
    AUDIO_EXTS = {
        ".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac", ".opus", ".weba",
    }
    VIDEO_EXTS = {
        ".mp4", ".webm", ".mov", ".m4v", ".ogv", ".3gp",
    }
    PDF_EXTS = {".pdf"}
    HTML_EXTS = {".html", ".htm"}
    MARKDOWN_EXTS = {".md", ".markdown"}
    CSV_EXTS = {".csv", ".tsv"}
    JSON_EXTS = {".json"}
    DOCX_EXTS = {".docx", ".docm"}
    XLSX_EXTS = {".xlsx", ".xlsm"}
    PPTX_EXTS = {".pptx"}
    LEGACY_OFFICE_EXTS = {".doc", ".xls", ".ppt", ".odt", ".ods", ".odp"}
    TEXT_EXTS = {
        ".txt", ".text", ".log", ".ini", ".cfg", ".conf", ".toml", ".yaml", ".yml",
        ".xml", ".css", ".scss", ".sass", ".less", ".js", ".mjs", ".cjs", ".ts",
        ".tsx", ".jsx", ".vue", ".svelte", ".py", ".rb", ".php", ".java", ".kt",
        ".kts", ".go", ".rs", ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".cs",
        ".swift", ".sql", ".sh", ".bash", ".zsh", ".bat", ".cmd", ".ps1", ".pl",
        ".lua", ".r", ".dart", ".scala", ".groovy", ".gradle", ".properties",
        ".env", ".diff", ".patch", ".tex", ".rst", ".srt", ".vtt", ".ass",
    }
    SPECIAL_TEXT_NAMES = {
        "dockerfile", "makefile", "license", "licence", "readme", "procfile",
        "gemfile", "rakefile", "vagrantfile", ".env", ".gitignore",
        ".gitattributes", ".dockerignore", ".editorconfig", ".npmrc", ".babelrc",
        ".eslintrc",
    }

    _SAFE_URL = re.compile(r"^(?:https?:|mailto:|#|/|\.)", re.IGNORECASE)
    _HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
    _RULE_RE = re.compile(r"^([-*_])\1{2,}\s*$")
    _LIST_RE = re.compile(r"^(\s*)([-*+]|\d+\.)\s+(.*)$")

    def __init__(self, down_dir):
        self.down_dir = Path(down_dir)

    # ---------------- 格式识别 ----------------
    @staticmethod
    def _split(filename):
        name = Path(filename).name.lower()
        return name, Path(name).suffix

    def describe(self, filename):
        name, ext = self._split(filename)
        if ext in self.IMAGE_EXTS:
            return {"mode": "image", "kind": "图片"}
        if ext in self.AUDIO_EXTS:
            return {"mode": "audio", "kind": "音频"}
        if ext in self.VIDEO_EXTS:
            return {"mode": "video", "kind": "视频"}
        if ext in self.PDF_EXTS:
            return {"mode": "pdf", "kind": "PDF 文档"}
        if ext in self.HTML_EXTS:
            return {"mode": "html-sandbox", "kind": "网页"}
        if ext in self.MARKDOWN_EXTS:
            return {"mode": "markdown", "kind": "Markdown 文档"}
        if ext in self.CSV_EXTS:
            return {"mode": "csv", "kind": "表格数据"}
        if ext in self.JSON_EXTS:
            return {"mode": "json", "kind": "JSON 数据"}
        if ext in self.DOCX_EXTS:
            return {"mode": "docx", "kind": "Word 文档"}
        if ext in self.XLSX_EXTS:
            return {"mode": "xlsx", "kind": "Excel 表格"}
        if ext in self.PPTX_EXTS:
            return {"mode": "pptx", "kind": "PPT 演示文稿"}
        if ext in self.LEGACY_OFFICE_EXTS:
            return {"mode": "office-fallback", "kind": "Office 文档"}
        if ext in self.TEXT_EXTS or name in self.SPECIAL_TEXT_NAMES:
            return {"mode": "text", "kind": "文本"}
        return {"mode": "download-only", "kind": "文件"}

    # ---------------- 预览页面数据 ----------------
    def build_view(self, filename, path):
        """汇总预览页所需的全部信息；不能渲染时回退为纯下载提示。"""
        info = self.describe(filename)
        stat = path.stat()
        context = {
            "filename": filename,
            "name": Path(filename).name,
            "mode": info["mode"],
            "kind": info["kind"],
            "size_text": self._size_text(stat.st_size),
            "modified_text": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "html": None,
            "truncated": False,
        }
        renderers = {
            "text": self._render_text,
            "markdown": self._render_markdown,
            "csv": self._render_csv,
            "json": self._render_json,
            "docx": self._render_docx,
            "xlsx": self._render_xlsx,
            "pptx": self._render_pptx,
        }
        renderer = renderers.get(context["mode"])
        if renderer is not None:
            rendered = renderer(path)
            if rendered is None:
                context["mode"] = "download-only"
                context["kind"] = "文件"
            else:
                context["html"], context["truncated"] = rendered
        return context

    @staticmethod
    def _size_text(size):
        if size < 1024:
            return f"{size} B"
        if size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        return f"{size / (1024 * 1024):.1f} MB"

    @staticmethod
    def _read_text(path):
        try:
            raw = path.read_bytes()
        except OSError:
            return None
        truncated = len(raw) > MAX_TEXT_BYTES
        raw = raw[:MAX_TEXT_BYTES]
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        return raw.decode("utf-8", errors="replace"), truncated

    # ---------------- 文本类渲染 ----------------
    def _render_text(self, path):
        loaded = self._read_text(path)
        if loaded is None:
            return None
        text, truncated = loaded
        return f"<pre class='preview-text'>{html_escape(text)}</pre>", truncated

    def _render_json(self, path):
        loaded = self._read_text(path)
        if loaded is None:
            return None
        text, truncated = loaded
        try:
            pretty = json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except ValueError:
            pretty = text
        return f"<pre class='preview-text'>{html_escape(pretty)}</pre>", truncated

    def _render_csv(self, path):
        loaded = self._read_text(path)
        if loaded is None:
            return None
        text, truncated = loaded
        delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
        rows = []
        try:
            for index, row in enumerate(csv.reader(io.StringIO(text), delimiter=delimiter)):
                if index >= MAX_TABLE_ROWS:
                    truncated = True
                    break
                rows.append(row[:MAX_TABLE_COLS])
        except csv.Error:
            return None
        if not rows:
            return "<p class='preview-empty-text'>（空表格）</p>", truncated
        return self._table_html(rows[0], rows[1:]), truncated

    @staticmethod
    def _table_html(head, body):
        header = "".join(f"<th>{html_escape(cell)}</th>" for cell in head)
        rows = "".join(
            "<tr>" + "".join(f"<td>{html_escape(cell)}</td>" for cell in row) + "</tr>"
            for row in body
        )
        return (
            "<div class='preview-table-wrap'><table class='preview-table'>"
            f"<thead><tr>{header}</tr></thead><tbody>{rows}</tbody>"
            "</table></div>"
        )

    def _render_markdown(self, path):
        loaded = self._read_text(path)
        if loaded is None:
            return None
        text, truncated = loaded
        return f"<div class='preview-doc markdown-body'>{self._markdown_to_html(text)}</div>", truncated

    def _markdown_to_html(self, text):
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        blocks = []
        index = 0
        total = len(lines)
        while index < total:
            line = lines[index]
            stripped = line.strip()
            if stripped.startswith("```"):
                index += 1
                code = []
                while index < total and not lines[index].strip().startswith("```"):
                    code.append(lines[index])
                    index += 1
                index += 1
                blocks.append(
                    "<pre class='md-code'><code>" + html_escape("\n".join(code)) + "</code></pre>"
                )
                continue
            if not stripped:
                index += 1
                continue
            heading = self._HEADING_RE.match(stripped)
            if heading:
                level = len(heading.group(1))
                blocks.append(f"<h{level}>{self._md_inline(heading.group(2))}</h{level}>")
                index += 1
                continue
            if self._RULE_RE.match(stripped):
                blocks.append("<hr>")
                index += 1
                continue
            if stripped.startswith(">"):
                quote = []
                while index < total and lines[index].strip().startswith(">"):
                    quote.append(lines[index].strip()[1:].strip())
                    index += 1
                blocks.append("<blockquote>" + self._md_inline(" ".join(quote)) + "</blockquote>")
                continue
            if self._LIST_RE.match(line):
                block, index = self._markdown_list(lines, index)
                blocks.append(block)
                continue
            paragraph = [stripped]
            index += 1
            while index < total:
                following = lines[index].strip()
                if (
                    not following
                    or following.startswith("```")
                    or following.startswith(">")
                    or self._HEADING_RE.match(following)
                    or self._RULE_RE.match(following)
                    or self._LIST_RE.match(lines[index])
                ):
                    break
                paragraph.append(following)
                index += 1
            blocks.append("<p>" + self._md_inline(" ".join(paragraph)) + "</p>")
        return "\n".join(blocks)

    def _markdown_list(self, lines, start):
        first = self._LIST_RE.match(lines[start])
        ordered = first.group(2)[0].isdigit()
        items = []
        index = start
        while index < len(lines):
            match = self._LIST_RE.match(lines[index])
            if not match:
                break
            items.append(self._md_inline(match.group(3)))
            index += 1
        tag = "ol" if ordered else "ul"
        return (f"<{tag}>" + "".join(f"<li>{item}</li>" for item in items) + f"</{tag}>", index)

    @classmethod
    def _md_inline(cls, text):
        escaped = html_escape(text)
        codes = []

        def stash(match):
            codes.append(html_escape(match.group(1)))
            return f"\x00{len(codes) - 1}\x00"

        escaped = re.sub(r"`([^`]+)`", stash, escaped)
        escaped = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", cls._md_image, escaped)
        escaped = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", cls._md_link, escaped)
        escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"__([^_]+)__", r"<strong>\1</strong>", escaped)
        escaped = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", escaped)
        escaped = escaped.replace("\n", "<br>")
        for position, code in enumerate(codes):
            escaped = escaped.replace(f"\x00{position}\x00", f"<code>{code}</code>")
        return escaped

    @classmethod
    def _md_link(cls, match):
        label, url = match.group(1), match.group(2)
        if not cls._SAFE_URL.match(url):
            return label
        return f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>'

    @classmethod
    def _md_image(cls, match):
        alt, url = match.group(1), match.group(2)
        if not cls._SAFE_URL.match(url):
            return alt
        return f'<img class="md-image" alt="{alt}" src="{url}">'

    # ---------------- Office 渲染 ----------------
    def _render_docx(self, path):
        try:
            with zipfile.ZipFile(path) as archive:
                xml = archive.read("word/document.xml")
        except (KeyError, OSError, zipfile.BadZipFile):
            return None
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError:
            return None
        paragraphs = []
        for paragraph in root.iter(f"{WORD_NS}p"):
            parts = []
            for node in paragraph.iter():
                if node.tag == f"{WORD_NS}t" and node.text:
                    parts.append(node.text)
                elif node.tag == f"{WORD_NS}tab":
                    parts.append("\t")
                elif node.tag in (f"{WORD_NS}br", f"{WORD_NS}cr"):
                    parts.append("\n")
            text = "".join(parts)
            if text.strip():
                body = html_escape(text).replace("\n", "<br>")
                paragraphs.append(f"<p>{body}</p>")
            else:
                paragraphs.append("<p class='docx-gap'>&nbsp;</p>")
        if not paragraphs:
            return None
        truncated = len(paragraphs) > MAX_DOCX_PARAGRAPHS
        return (
            "<div class='preview-doc docx-body'>" + "".join(paragraphs[:MAX_DOCX_PARAGRAPHS]) + "</div>",
            truncated,
        )

    def _render_xlsx(self, path):
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                shared = self._xlsx_shared_strings(archive, names)
                sheets = sorted(
                    (name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)),
                    key=lambda item: int(re.search(r"(\d+)", Path(item).stem).group(1)),
                )
                if not sheets:
                    return None
                blocks = []
                truncated = False
                for index, name in enumerate(sheets[:20], start=1):
                    rows = self._xlsx_rows(archive.read(name), shared)
                    if not rows:
                        blocks.append(f"<h3 class='sheet-title'>工作表 {index}</h3><p class='preview-empty-text'>（空工作表）</p>")
                        continue
                    more = len(rows) > MAX_OFFICE_ROWS
                    truncated = truncated or more
                    table = self._table_html(rows[0], rows[1:MAX_OFFICE_ROWS])
                    blocks.append(f"<h3 class='sheet-title'>工作表 {index}</h3>{table}")
        except (KeyError, OSError, zipfile.BadZipFile, ElementTree.ParseError):
            return None
        return "<div class='preview-doc'>" + "".join(blocks) + "</div>", truncated

    @staticmethod
    def _xlsx_shared_strings(archive, names):
        if "xl/sharedStrings.xml" not in names:
            return []
        try:
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        except (ElementTree.ParseError, KeyError):
            return []
        return [
            "".join(node.text or "" for node in item.iter(f"{SHEET_NS}t"))
            for item in root.iter(f"{SHEET_NS}si")
        ]

    def _xlsx_rows(self, xml, shared):
        try:
            root = ElementTree.fromstring(xml)
        except ElementTree.ParseError:
            return []
        rows = []
        for row in root.iter(f"{SHEET_NS}row"):
            cells = {}
            for cell in row.iter(f"{SHEET_NS}c"):
                column = self._column_index(cell.get("r") or "")
                cell_type = cell.get("t")
                if cell_type == "inlineStr":
                    value = "".join(node.text or "" for node in cell.iter(f"{SHEET_NS}t"))
                else:
                    node = cell.find(f"{SHEET_NS}v")
                    raw = node.text if node is not None and node.text else ""
                    if cell_type == "s" and raw.isdigit():
                        index = int(raw)
                        value = shared[index] if index < len(shared) else ""
                    else:
                        value = raw
                cells[column] = value
            if not cells:
                rows.append([])
                continue
            width = min(max(cells) + 1, MAX_OFFICE_COLS)
            rows.append([cells.get(index, "") for index in range(width)])
        return rows

    @staticmethod
    def _column_index(ref):
        letters = "".join(char for char in ref if char.isalpha()).upper()
        index = 0
        for char in letters:
            index = index * 26 + (ord(char) - 64)
        return max(index - 1, 0)

    def _render_pptx(self, path):
        try:
            with zipfile.ZipFile(path) as archive:
                slides = sorted(
                    (name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
                    key=lambda item: int(re.search(r"(\d+)", Path(item).stem).group(1)),
                )
                if not slides:
                    return None
                blocks = []
                for index, name in enumerate(slides[:MAX_SLIDES], start=1):
                    root = ElementTree.fromstring(archive.read(name))
                    lines = [
                        node.text.strip()
                        for node in root.iter(f"{DRAWING_NS}t")
                        if node.text and node.text.strip()
                    ]
                    body = "".join(f"<p>{html_escape(line)}</p>" for line in lines)
                    if not body:
                        body = "<p class='docx-gap'>（本页无文字）</p>"
                    blocks.append(f"<section class='preview-slide'><h3>第 {index} 页</h3>{body}</section>")
        except (KeyError, OSError, zipfile.BadZipFile, ElementTree.ParseError):
            return None
        return "<div class='preview-doc'>" + "".join(blocks) + "</div>", len(slides) > MAX_SLIDES
