from pathlib import Path

import pytest

from src.media import save_image
from src.ingest.readers import extract_md_images


def test_save_image_writes_file_and_returns_path(tmp_path, monkeypatch):
    monkeypatch.setattr("src.media.settings", type("S", (), {"MEDIA_DIR": str(tmp_path)})())

    data = b"\x89PNG\r\n\x1a\nfake-image-data"
    result = save_image(data, "test-slug", "photo.png")

    assert result == "test-slug/photo.png"
    written = (tmp_path / "test-slug" / "photo.png").read_bytes()
    assert written == data


def test_save_image_creates_nested_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr("src.media.settings", type("S", (), {"MEDIA_DIR": str(tmp_path)})())

    save_image(b"data", "new-slug", "img.jpg")

    assert (tmp_path / "new-slug" / "img.jpg").exists()


def test_save_image_strips_path_traversal_in_filename(tmp_path, monkeypatch):
    monkeypatch.setattr("src.media.settings", type("S", (), {"MEDIA_DIR": str(tmp_path)})())

    result = save_image(b"x", "slug", "../../../etc/passwd")

    assert result == "slug/passwd"
    assert (tmp_path / "slug" / "passwd").exists()
    assert not (tmp_path.parent.parent.parent / "etc" / "passwd").exists()


def test_save_image_strips_path_traversal_in_slug(tmp_path, monkeypatch):
    monkeypatch.setattr("src.media.settings", type("S", (), {"MEDIA_DIR": str(tmp_path)})())

    result = save_image(b"x", "../evil", "img.png")

    assert result == "evil/img.png"
    assert (tmp_path / "evil" / "img.png").exists()


def test_save_image_rejects_empty_after_normalization(tmp_path, monkeypatch):
    monkeypatch.setattr("src.media.settings", type("S", (), {"MEDIA_DIR": str(tmp_path)})())

    with pytest.raises(ValueError):
        save_image(b"x", "slug", "/")


def test_save_image_path_format_matches_extract_md_images(tmp_path, monkeypatch):
    """Both producers must emit ``<slug>/<filename>`` — no ``media/`` prefix.

    Templates render path as ``/media/{{ item.path }}``; the static mount
    already prepends ``/media``. Any divergence in producer output makes the
    URL ``/media/media/...`` and 404s.
    """
    monkeypatch.setattr("src.media.settings", type("S", (), {"MEDIA_DIR": str(tmp_path)})())
    # config.MEDIA_DIR is also referenced by readers.extract_md_images
    monkeypatch.setattr("src.ingest.readers.settings", type("S", (), {"MEDIA_DIR": str(tmp_path)})())

    # save_image side
    saved_path = save_image(b"x", "rumor-A", "shot.png")
    assert not saved_path.startswith("media/"), f"save_image leaked prefix: {saved_path!r}"

    # extract_md_images side: prepare an md file referencing an image already inside MEDIA_DIR
    img_dir = tmp_path / "rumor-B"
    img_dir.mkdir()
    img = img_dir / "pic.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0")  # JPEG magic
    md = tmp_path / "src.md"
    md.write_text(f"![cap](rumor-B/pic.jpg)\n", encoding="utf-8")

    items = extract_md_images(md)
    assert len(items) == 1
    assert not items[0].path.startswith("media/"), f"extract_md_images leaked prefix: {items[0].path!r}"
    # And both producers point at the same physical file when given the same slug/filename pair
    assert items[0].path == "rumor-B/pic.jpg"
