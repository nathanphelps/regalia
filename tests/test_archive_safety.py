"""Extraction must stay inside the directory it was given.

Archives come from the internet. An entry named "../../.bashrc" is the oldest
trick there is, and both backends happen to defend against it — the standard
library rewrites the path and 7z refuses to climb out. That is a property worth
holding on to rather than rediscovering, because the backend is chosen at
runtime and a future one might not.
"""

from __future__ import annotations

import zipfile

import pytest

from regalia import archive

ESCAPES = {
    "../../escaped.txt": b"no",
    "/absolute.txt": b"no",
    "nested/../../also-escaped.txt": b"no",
    "keeper_9999999_P.pak": b"yes",
}


@pytest.fixture(params=["7z", "python"])
def backend(request, monkeypatch):
    if request.param == "7z" and not archive.seven_zip_command():
        pytest.skip("no 7z command on this machine")
    monkeypatch.setenv(archive.ENV_BACKEND, request.param)
    archive.reset_extractor()
    yield request.param
    archive.reset_extractor()


def test_no_entry_escapes_the_destination(tmp_path, backend):
    source = tmp_path / "evil.zip"
    with zipfile.ZipFile(source, "w") as handle:
        for name, data in ESCAPES.items():
            handle.writestr(name, data)
    destination = tmp_path / "out"
    outside = tmp_path / "canary"
    outside.mkdir()

    archive.extract_tree(source, destination)

    written = [path for path in destination.rglob("*") if path.is_file()]
    assert written, "nothing was extracted at all"
    for path in written:
        assert destination in path.parents, f"{path} escaped {destination}"
    assert list(outside.iterdir()) == []
    assert not (tmp_path / "escaped.txt").exists()
    assert not (tmp_path / "absolute.txt").exists()


def test_the_real_content_still_arrives(tmp_path, backend):
    source = tmp_path / "evil.zip"
    with zipfile.ZipFile(source, "w") as handle:
        for name, data in ESCAPES.items():
            handle.writestr(name, data)

    archive.extract_tree(source, tmp_path / "out")

    names = {path.name for path in (tmp_path / "out").rglob("*") if path.is_file()}
    assert "keeper_9999999_P.pak" in names
