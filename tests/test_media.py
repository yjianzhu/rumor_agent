from pathlib import Path

from src.media import save_image


def test_save_image_writes_file_and_returns_path(tmp_path, monkeypatch):
    monkeypatch.setattr("src.media.settings", type("S", (), {"MEDIA_DIR": str(tmp_path)})())

    data = b"\x89PNG\r\n\x1a\nfake-image-data"
    result = save_image(data, "test-slug", "photo.png")

    assert result == "media/test-slug/photo.png"
    written = (tmp_path / "test-slug" / "photo.png").read_bytes()
    assert written == data


def test_save_image_creates_nested_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr("src.media.settings", type("S", (), {"MEDIA_DIR": str(tmp_path)})())

    save_image(b"data", "new-slug", "img.jpg")

    assert (tmp_path / "new-slug" / "img.jpg").exists()
