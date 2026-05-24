from pathlib import Path

import pytest

from worldcup.config import get_settings
from worldcup.render.writer import write_digest


@pytest.mark.asyncio
async def test_write_digest_writes_dated_file_and_pickup(tmp_path, monkeypatch):
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    pickup = tmp_path / "out" / "latest.md"
    monkeypatch.setenv("DIGEST_OUTPUT_DIR", str(output_dir))
    monkeypatch.setenv("WHATSAPP_PICKUP_PATH", str(pickup))
    get_settings.cache_clear()

    path = await write_digest("hello world\n", date_str="2026-05-21")

    assert path == output_dir / "2026-05-21.md"
    assert (output_dir / "2026-05-21.md").read_text() == "hello world\n"
    assert pickup.read_text() == "hello world\n"


@pytest.mark.asyncio
async def test_write_digest_creates_missing_dirs(tmp_path, monkeypatch):
    deep = tmp_path / "a" / "b" / "c"
    monkeypatch.setenv("DIGEST_OUTPUT_DIR", str(deep))
    monkeypatch.setenv("WHATSAPP_PICKUP_PATH", str(deep / "latest.md"))
    get_settings.cache_clear()

    path = await write_digest("x", date_str="2026-05-22")

    assert path.exists()
    assert (deep / "latest.md").read_text() == "x"
