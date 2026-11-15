from pathlib import Path

from netu_app.file_service import FileService


def test_rejects_path_traversal(tmp_path):
    service = FileService(tmp_path)

    assert service.resolve_visible("../hack.txt") is None


def test_duplicate_upload_is_renamed(tmp_path):
    service = FileService(tmp_path)

    first_name = service.make_upload_name("report.pdf")
    Path(tmp_path / first_name).write_text("a", encoding="utf-8")
    second_name = service.make_upload_name("report.pdf")

    assert second_name != "report.pdf"
    assert second_name.startswith("report_")


def test_list_files_returns_stable_etag(tmp_path):
    service = FileService(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")

    payload = service.list_files()

    assert payload["etag"]
    assert payload["files"][0]["name"] == "a.txt"
    assert payload["hidden"] == []


def test_hide_moves_file_into_hidden_dir(tmp_path):
    service = FileService(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")

    assert service.hide("a.txt") is True

    assert not (tmp_path / "a.txt").exists()
    assert (tmp_path / ".hidden" / "a.txt").exists()
    payload = service.list_files()
    assert payload["files"] == []
    assert payload["hidden"][0]["name"] == "a.txt"


def test_restore_moves_hidden_file_back(tmp_path):
    service = FileService(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    service.hide("a.txt")

    assert service.restore("a.txt") is True

    assert (tmp_path / "a.txt").exists()
    assert not (tmp_path / ".hidden" / "a.txt").exists()


def test_purge_removes_file_permanently(tmp_path):
    service = FileService(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    service.hide("a.txt")

    assert service.purge("a.txt") is True

    assert not (tmp_path / ".hidden" / "a.txt").exists()
    assert not (tmp_path / "a.txt").exists()


def test_file_note_is_stored_and_listed(tmp_path):
    service = FileService(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")

    assert service.write_note("a.txt", "  重要文件  ") is True

    payload = service.list_files()
    assert payload["files"][0]["note"] == "重要文件"
    assert (tmp_path / ".notes.json").exists()


def test_write_note_rejects_missing_file(tmp_path):
    service = FileService(tmp_path)

    assert service.write_note("ghost.txt", "x") is False
    assert not (tmp_path / ".notes.json").exists()


def test_notes_file_is_not_listed_as_a_file(tmp_path):
    service = FileService(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    service.write_note("a.txt", "note")

    names = [item["name"] for item in service.list_files()["files"]]

    assert names == ["a.txt"]


def test_clearing_note_removes_notes_file(tmp_path):
    service = FileService(tmp_path)
    (tmp_path / "a.txt").write_text("hello", encoding="utf-8")
    service.write_note("a.txt", "note")

    assert service.write_note("a.txt", "   ") is True

    assert not (tmp_path / ".notes.json").exists()
    assert service.list_files()["files"][0]["note"] == ""
