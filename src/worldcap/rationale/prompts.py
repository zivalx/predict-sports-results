"""Prompt templates for rationale generation.

Kept in a separate module so prompts can be tuned independently of the
orchestration logic that calls them.
"""

from dataclasses import dataclass


@dataclass
class MatchPromptContext:
    home_name: str
    away_name: str
    stage: str
    group_label: str | None
    kickoff_iso: str
    home_rating: float
    away_rating: float
    our_p_home: float
    our_p_draw: float
    our_p_away: float
    poly_p_home: float | None
    poly_p_draw: float | None
    poly_p_away: float | None
    edge_vs_poly: float
    home_recent_news: list[str]
    away_recent_news: list[str]
    home_sentiment: float | None
    away_sentiment: float | None


def build_match_rationale_prompt(ctx: MatchPromptContext) -> str:
    """Produce a structured prompt that asks Claude for a 2-3 sentence paragraph.

    The format is deliberately strict: a single paragraph, no headers, no
    bullet points, no parenthetical commentary — just analysis.
    """
    lines: list[str] = []
    lines.append(
        f"Write a 2-3 sentence analysis paragraph for the upcoming football match "
        f"{ctx.home_name} vs {ctx.away_name} ({ctx.stage}"
        + (f", Group {ctx.group_label}" if ctx.group_label else "")
        + f") on {ctx.kickoff_iso}."
    )
    lines.append("")
    lines.append("CONTEXT:")
    lines.append(f"- Elo ratings: {ctx.home_name} {ctx.home_rating:.0f}, {ctx.away_name} {ctx.away_rating:.0f}")
    lines.append(
        f"- Our model probability: {ctx.home_name} {ctx.our_p_home*100:.0f}%, "
        f"draw {ctx.our_p_draw*100:.0f}%, {ctx.away_name} {ctx.our_p_away*100:.0f}%"
    )
    if ctx.poly_p_home is not None:
        lines.append(
            f"- Polymarket: {ctx.home_name} {ctx.poly_p_home*100:.0f}%, "
            f"draw {(ctx.poly_p_draw or 0)*100:.0f}%, {ctx.away_name} {(ctx.poly_p_away or 0)*100:.0f}%"
        )
        lines.append(f"- Edge vs market on {ctx.home_name}: {ctx.edge_vs_poly*100:+.0f}pp")
    else:
        lines.append("- Polymarket: no per-match market available")
    if ctx.home_sentiment is not None:
        lines.append(f"- {ctx.home_name} sentiment (recent fan/press): {ctx.home_sentiment:+.2f}")
    if ctx.away_sentiment is not None:
        lines.append(f"- {ctx.away_name} sentiment (recent fan/press): {ctx.away_sentiment:+.2f}")
    if ctx.home_recent_news:
        lines.append(f"- Recent {ctx.home_name} headlines:")
        for headline in ctx.home_recent_news[:3]:
            lines.append(f"  - {headline}")
    if ctx.away_recent_news:
        lines.append(f"- Recent {ctx.away_name} headlines:")
        for headline in ctx.away_recent_news[:3]:
            lines.append(f"  - {headline}")
    lines.append("")
    lines.append(
        "REQUIREMENTS: Write exactly 2-3 sentences as a single paragraph. "
        "Reference the most concrete facts from the context (a specific news item, "
        "a notable rating gap, or a significant edge). Don't restate the probabilities "
        "verbatim. Don't use bullet points or headers. Don't begin with 'In this match' "
        "or similar throat-clearing."
    )
    return "\n".join(lines)
