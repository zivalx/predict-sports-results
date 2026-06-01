"""Render the dashboard + JSON API to a directory of static files.

Uses ASGITransport against the in-process FastAPI app to fetch each
page, then writes the response body to disk. The output directory is
self-contained — drop it into any static host (Cloudflare Pages,
Netlify, S3, etc).

Generated structure:
    <out>/
      index.html
      tournament.html
      golden-boot.html
      match/<id>.html
      static/dashboard.css
      api/
        tournament_outlook.json
        golden_boot_race.json
        match_forecast/<id>.json
        team_overview/<name>.json
"""

from pathlib import Path

from httpx import ASGITransport, AsyncClient
from sqlmodel import select

from worldcup.api.app import build_app
from worldcup.db import get_session
from worldcup.models import Match, Team


async def export_static(output_dir: Path, base_url: str = "") -> dict[str, int]:
    """Render all dashboard pages + JSON snapshots to `output_dir`.

    `base_url`, if provided, is appended to the page footers so users
    have a canonical URL for the deployment (e.g. https://worldcup.zivalx.com).
    Currently the templates don't have a configurable base_url slot;
    this parameter is reserved for future use and a meta tag.

    Returns counts of files written by kind.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    app = build_app()
    transport = ASGITransport(app=app)
    counts = {"pages": 0, "json": 0, "css": 0}

    async with AsyncClient(transport=transport, base_url="http://internal") as client:
        # Top-level pages
        for path, filename in [
            ("/", "index.html"),
            ("/tournament", "tournament.html"),
            ("/golden-boot", "golden-boot.html"),
            ("/bets", "bets.html"),
            ("/results", "results.html"),
        ]:
            r = await client.get(path)
            r.raise_for_status()
            content = _rewrite_links_for_static(r.text, base_url=base_url)
            (output_dir / filename).write_text(content)
            counts["pages"] += 1

        # Per-match pages — enumerate match ids from the DB
        match_ids = []
        team_names = []
        async with get_session() as session:
            matches = (await session.execute(select(Match))).scalars().all()
            match_ids = [m.id for m in matches if m.id is not None]
            teams = (await session.execute(select(Team))).scalars().all()
            team_names = [t.name for t in teams]

        match_dir = output_dir / "match"
        match_dir.mkdir(parents=True, exist_ok=True)
        for mid in match_ids:
            r = await client.get(f"/match/{mid}")
            if r.status_code != 200:
                continue
            content = _rewrite_links_for_static(r.text, base_url=base_url)
            (match_dir / f"{mid}.html").write_text(content)
            counts["pages"] += 1

        # CSS
        (output_dir / "static").mkdir(parents=True, exist_ok=True)
        r = await client.get("/static/dashboard.css")
        r.raise_for_status()
        (output_dir / "static" / "dashboard.css").write_text(r.text)
        counts["css"] += 1

        # JSON API snapshots
        api_dir = output_dir / "api"
        api_dir.mkdir(parents=True, exist_ok=True)

        r = await client.get("/api/tournament_outlook?top_n=50")
        r.raise_for_status()
        (api_dir / "tournament_outlook.json").write_text(r.text)
        counts["json"] += 1

        r = await client.get("/api/golden_boot_race?top_n=50")
        r.raise_for_status()
        (api_dir / "golden_boot_race.json").write_text(r.text)
        counts["json"] += 1

        # Per-match forecasts (use home_team + away_team query — fetch by IDs is easier; use match detail endpoint shape via /api/match_forecast?home_team=X&away_team=Y)
        # The MCP endpoint requires team names; iterate matches and look up names
        async with get_session() as session:
            matches = (await session.execute(select(Match))).scalars().all()
            teams_by_id = {
                t.id: t for t in (await session.execute(select(Team))).scalars().all()
            }
        mf_dir = api_dir / "match_forecast"
        mf_dir.mkdir(parents=True, exist_ok=True)
        for m in matches:
            if m.home_team_id is None or m.away_team_id is None:
                continue
            h = teams_by_id.get(m.home_team_id)
            a = teams_by_id.get(m.away_team_id)
            if h is None or a is None:
                continue
            r = await client.get(
                "/api/match_forecast",
                params={"home_team": h.name, "away_team": a.name},
            )
            if r.status_code != 200:
                continue
            (mf_dir / f"{m.id}.json").write_text(r.text)
            counts["json"] += 1

        # Per-team overviews
        ov_dir = api_dir / "team_overview"
        ov_dir.mkdir(parents=True, exist_ok=True)
        for name in team_names:
            r = await client.get("/api/team_overview", params={"team_name": name})
            if r.status_code != 200:
                continue
            safe_name = name.replace("/", "_").replace(" ", "_")
            (ov_dir / f"{safe_name}.json").write_text(r.text)
            counts["json"] += 1

    return counts


def _rewrite_links_for_static(html: str, base_url: str = "") -> str:
    """Rewrite dashboard HTML so links resolve correctly when served as static files.

    Currently the templates emit:
      href="/"               → href="./index.html"   (or "../index.html" for nested pages)
      href="/tournament"     → href="./tournament.html"
      href="/golden-boot"    → href="./golden-boot.html"
      href="/match/<id>"     → href="./match/<id>.html"  (relative from index; relative from match/N.html is "N.html")
      href="/static/..."     → href="./static/..."

    Naive approach: replace from-root paths with relative ones. For pages
    nested under /match/, the parent path needs ../ prefix. Since this
    function doesn't know the depth of the rendered page, we use a simple
    convention: always emit /worldcup/ as the prefix and rely on the CF
    Pages deployment to mount the site at the root or at /worldcup/.

    For v0 the simplest fix is to leave the absolute paths alone IF the
    target host is `worldcup.zivalx.com` (subdomain — root-mounted). Then
    no rewriting needed; links like href="/tournament" naturally work.

    So this function is a no-op for v0 but is a hook for future use.
    """
    # Rewrite nav links so they resolve as static .html files.
    html = html.replace('href="/tournament"', 'href="/tournament.html"')
    html = html.replace('href="/golden-boot"', 'href="/golden-boot.html"')
    html = html.replace('href="/bets"', 'href="/bets.html"')
    html = html.replace('href="/results"', 'href="/results.html"')
    # /match/<id> links → /match/<id>.html
    import re
    html = re.sub(r'href="/match/(\d+)"', r'href="/match/\1.html"', html)

    # Optional: inject a <meta> hint for the canonical URL.
    if base_url:
        meta_tag = f'<meta name="canonical-base" content="{base_url}">'
        html = html.replace("<head>", f"<head>\n  {meta_tag}", 1)
    return html
