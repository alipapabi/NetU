import zipfile

from netu_app.preview_service import PreviewService


def make_docx(path, paragraphs):
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" for text in paragraphs)
        + "</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document)


def make_xlsx(path, rows):
    shared = []
    row_xml = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row):
            reference = f"{chr(65 + column_index)}{row_index}"
            shared.append(value)
            cells.append(f'<c r="{reference}" t="s"><v>{len(shared) - 1}</v></c>')
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>'
    )
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        + "".join(f"<si><t>{value}</t></si>" for value in shared)
        + "</sst>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def make_pptx(path, slides):
    with zipfile.ZipFile(path, "w") as archive:
        for index, lines in enumerate(slides, start=1):
            body = "".join(f"<a:p><a:r><a:t>{line}</a:t></a:r></a:p>" for line in lines)
            slide = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<p:sld xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
                f"<p:cSld><p:spTree>{body}</p:spTree></p:cSld></p:sld>"
            )
            archive.writestr(f"ppt/slides/slide{index}.xml", slide)


def test_html_uses_sandbox_mode(tmp_path):
    service = PreviewService(tmp_path)

    info = service.describe("demo.html")

    assert info["mode"] == "html-sandbox"


def test_text_file_uses_text_mode(tmp_path):
    service = PreviewService(tmp_path)

    info = service.describe("notes.txt")

    assert info["mode"] == "text"


def test_pdf_file_uses_embed_mode(tmp_path):
    service = PreviewService(tmp_path)

    info = service.describe("book.pdf")

    assert info["mode"] == "pdf"


def test_extended_formats_are_recognized(tmp_path):
    service = PreviewService(tmp_path)

    assert service.describe("photo.avif")["mode"] == "image"
    assert service.describe("photo.bmp")["mode"] == "image"
    assert service.describe("song.flac")["mode"] == "audio"
    assert service.describe("clip.m4v")["mode"] == "video"
    assert service.describe("script.py")["mode"] == "text"
    assert service.describe("Dockerfile")["mode"] == "text"
    assert service.describe(".env")["mode"] == "text"
    assert service.describe("readme.md")["mode"] == "markdown"
    assert service.describe("data.csv")["mode"] == "csv"
    assert service.describe("payload.json")["mode"] == "json"
    assert service.describe("report.docx")["mode"] == "docx"
    assert service.describe("sheet.xlsx")["mode"] == "xlsx"
    assert service.describe("deck.pptx")["mode"] == "pptx"
    assert service.describe("legacy.doc")["mode"] == "office-fallback"
    assert service.describe("bundle.bin")["mode"] == "download-only"


def test_text_view_is_escaped(tmp_path):
    service = PreviewService(tmp_path)
    path = tmp_path / "note.txt"
    path.write_text("<script>alert(1)</script>", encoding="utf-8")

    context = service.build_view("note.txt", path)

    assert context["mode"] == "text"
    assert "<script>" not in context["html"]
    assert "&lt;script&gt;" in context["html"]


def test_json_view_is_pretty_printed(tmp_path):
    service = PreviewService(tmp_path)
    path = tmp_path / "data.json"
    path.write_text('{"a":1,"b":[2,3]}', encoding="utf-8")

    context = service.build_view("data.json", path)

    assert context["mode"] == "json"
    assert "&quot;a&quot;: 1" in context["html"]


def test_csv_view_renders_a_table(tmp_path):
    service = PreviewService(tmp_path)
    path = tmp_path / "data.csv"
    path.write_text("name,age\nalice,30\nbob,25\n", encoding="utf-8")

    context = service.build_view("data.csv", path)

    assert context["mode"] == "csv"
    assert "<table class='preview-table'>" in context["html"]
    assert "<th>name</th>" in context["html"]
    assert "<td>alice</td>" in context["html"]


def test_markdown_view_renders_formatting(tmp_path):
    service = PreviewService(tmp_path)
    path = tmp_path / "doc.md"
    path.write_text("# 标题\n\n- **粗体** 项目\n\n`code`\n", encoding="utf-8")

    context = service.build_view("doc.md", path)

    assert context["mode"] == "markdown"
    assert "<h1>标题</h1>" in context["html"]
    assert "<strong>粗体</strong>" in context["html"]
    assert "<li>" in context["html"]


def test_markdown_view_blocks_unsafe_links(tmp_path):
    service = PreviewService(tmp_path)
    path = tmp_path / "doc.md"
    path.write_text("[点我](javascript:alert(1))", encoding="utf-8")

    context = service.build_view("doc.md", path)

    assert "javascript:" not in context["html"]
    assert "点我" in context["html"]


def test_docx_view_extracts_paragraphs(tmp_path):
    service = PreviewService(tmp_path)
    path = tmp_path / "report.docx"
    make_docx(path, ["第一段", "第二段"])

    context = service.build_view("report.docx", path)

    assert context["mode"] == "docx"
    assert "第一段" in context["html"]
    assert "第二段" in context["html"]


def test_xlsx_view_renders_sheet_table(tmp_path):
    service = PreviewService(tmp_path)
    path = tmp_path / "sheet.xlsx"
    make_xlsx(path, [["名称", "数量"], ["苹果", "3"]])

    context = service.build_view("sheet.xlsx", path)

    assert context["mode"] == "xlsx"
    assert "名称" in context["html"]
    assert "苹果" in context["html"]


def test_pptx_view_lists_slides(tmp_path):
    service = PreviewService(tmp_path)
    path = tmp_path / "deck.pptx"
    make_pptx(path, [["封面标题"], ["要点一", "要点二"]])

    context = service.build_view("deck.pptx", path)

    assert context["mode"] == "pptx"
    assert "第 1 页" in context["html"]
    assert "要点一" in context["html"]


def test_broken_office_file_falls_back_to_download(tmp_path):
    service = PreviewService(tmp_path)
    path = tmp_path / "broken.docx"
    path.write_bytes(b"not a zip archive")

    context = service.build_view("broken.docx", path)

    assert context["mode"] == "download-only"
    assert context["html"] is None
