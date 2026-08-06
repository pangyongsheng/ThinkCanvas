"""Tests for the video-file cleanup helpers.

These helpers live next to the storage layer so they can be unit-tested
without going through FastAPI / the async DB session.
"""
from __future__ import annotations

from pathlib import Path

from app.storage.conversations import (
    _delete_video_files,
    _video_url_to_path,
)


# ---------------------------------------------------------------------------
# _video_url_to_path
# ---------------------------------------------------------------------------

def test_video_url_to_path_handles_localhost_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.storage.conversations.MEDIA_ROOT", tmp_path
    )
    p = _video_url_to_path("http://localhost:8000/media/20260806/foo.mp4")
    assert p == (tmp_path / "20260806/foo.mp4").resolve()


def test_video_url_to_path_handles_127_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.storage.conversations.MEDIA_ROOT", tmp_path
    )
    p = _video_url_to_path("http://127.0.0.1:8000/media/foo/bar.mp4")
    assert p == (tmp_path / "foo/bar.mp4").resolve()


def test_video_url_to_path_handles_relative_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.storage.conversations.MEDIA_ROOT", tmp_path
    )
    p = _video_url_to_path("/media/legacy.mp4")
    assert p == (tmp_path / "legacy.mp4").resolve()


def test_video_url_to_path_returns_none_for_unknown_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.storage.conversations.MEDIA_ROOT", tmp_path
    )
    # Not a video URL we ever produce — must not crash.
    assert _video_url_to_path("") is None
    assert _video_url_to_path("https://example.com/foo.mp4") is None
    assert _video_url_to_path("not-a-url") is None


# ---------------------------------------------------------------------------
# _delete_video_files
# ---------------------------------------------------------------------------

def test_delete_video_files_removes_existing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.storage.conversations.MEDIA_ROOT", tmp_path
    )
    f1 = tmp_path / "a.mp4"
    f2 = tmp_path / "subdir" / "b.mp4"
    f2.parent.mkdir()
    f1.write_bytes(b"x")
    f2.write_bytes(b"y")

    n = _delete_video_files([
        f"http://localhost:8000/media/a.mp4",
        f"http://localhost:8000/media/subdir/b.mp4",
    ])
    assert n == 2
    assert not f1.exists()
    assert not f2.exists()


def test_delete_video_files_skips_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.storage.conversations.MEDIA_ROOT", tmp_path
    )
    f1 = tmp_path / "a.mp4"
    f1.write_bytes(b"x")

    # b.mp4 does not exist on disk; must not raise.
    n = _delete_video_files([
        f"http://localhost:8000/media/a.mp4",
        f"http://localhost:8000/media/missing.mp4",
    ])
    assert n == 1
    assert not f1.exists()


def test_delete_video_files_skips_unparseable_urls(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.storage.conversations.MEDIA_ROOT", tmp_path
    )
    f1 = tmp_path / "a.mp4"
    f1.write_bytes(b"x")

    n = _delete_video_files([
        "https://example.com/x.mp4",  # unknown shape
        "",                             # empty
        f"http://localhost:8000/media/a.mp4",  # good
    ])
    assert n == 1
    assert not f1.exists()


def test_delete_video_files_empty_list(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.storage.conversations.MEDIA_ROOT", tmp_path
    )
    assert _delete_video_files([]) == 0
