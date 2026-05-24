import json
from datetime import datetime, timezone

import pytest
from sqlmodel import select

from worldcap.db import get_session, init_db
from worldcap.models import (
    Competition,
    ForecastSnapshot,
    Match,
    MatchForecast,
    Team,
    TopScorerForecast,
    TournamentForecast,
)
from worldcap.render.static_export import export_static
from scripts.seed_competition import seed


@pytest.mark.asyncio
async def test_export_writes_pages_and_json(tmp_path):
    await init_db()
    await seed()

    as_of = datetime(2026, 5, 24, tzinfo=timezone.utc)
    async with get_session() as session:
        comp = (await session.execute(select(Competition))).scalar_one()
        session.add_all([
            Team(external_id=1, name="Brazil", country_code="BRA"),
            Team(external_id=2, name="France", country_code="FRA"),
        ])
        await session.flush()
        teams = {t.name: t for t in (await session.execute(select(Team))).scalars().all()}
        m = Match(
            external_id=1, competition_id=comp.id, stage="group", group_label="G",
            home_team_id=teams["Brazil"].id, away_team_id=teams["France"].id,
            kickoff_utc=datetime(2026, 6, 15, 20, 0, tzinfo=timezone.utc),
            status="SCHEDULED",
        )
        session.add(m)
        snap = ForecastSnapshot(
            competition_id=comp.id, snapshot_date=as_of,
            snapshot_trigger="manual", poly_odds_hash="x", model_state_hash="y",
            model_version="t",
        )
        session.add(snap)
        await session.flush()
        session.add_all([
            TournamentForecast(snapshot_id=snap.id, team_id=teams["Brazil"].id,
                               p_champion=0.20, p_runner_up=0.10, p_semi=0.30, p_top_group=0.55,
                               poly_p_champion=0.22, edge_vs_poly=-0.02),
        ])
        session.add(MatchForecast(
            snapshot_id=snap.id, match_id=m.id,
            p_home=0.40, p_draw=0.28, p_away=0.32,
            p_home_poly=0.45, p_draw_poly=0.27, p_away_poly=0.28,
            edge_vs_poly=-0.05, rationale_md="Brazil underrated.",
        ))
        await session.commit()
        await session.refresh(m)
        match_id = m.id

    out = tmp_path / "static_out"
    summary = await export_static(out, base_url="https://worldcup.example.com")

    # Top-level pages
    assert (out / "index.html").exists()
    assert (out / "tournament.html").exists()
    assert (out / "golden-boot.html").exists()
    # Per-match page
    assert (out / "match" / f"{match_id}.html").exists()
    # CSS
    assert (out / "static" / "dashboard.css").exists()
    # JSON
    assert (out / "api" / "tournament_outlook.json").exists()
    assert (out / "api" / "golden_boot_race.json").exists()
    assert (out / "api" / "match_forecast" / f"{match_id}.json").exists()
    assert (out / "api" / "team_overview" / "Brazil.json").exists()

    # Sanity-check JSON content
    outlook = json.loads((out / "api" / "tournament_outlook.json").read_text())
    assert len(outlook["entries"]) == 1
    assert outlook["entries"][0]["team"] == "Brazil"

    # canonical-base meta tag injected
    html = (out / "index.html").read_text()
    assert "canonical-base" in html
    assert "worldcup.example.com" in html

    # Summary returned counts
    assert summary["pages"] >= 4  # 3 top-level + at least 1 match
    assert summary["json"] >= 4   # outlook + boot + 1 match + 1 team
