from pathlib import Path

from worldcap.config import get_settings


async def write_digest(text: str, date_str: str) -> Path:
    settings = get_settings()
    settings.digest_output_dir.mkdir(parents=True, exist_ok=True)
    settings.whatsapp_pickup_path.parent.mkdir(parents=True, exist_ok=True)

    dated = settings.digest_output_dir / f"{date_str}.md"
    dated.write_text(text)
    settings.whatsapp_pickup_path.write_text(text)
    return dated
