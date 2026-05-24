"""WC 2026 official bracket template.

Sources:
  Primary:   https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_knockout_stage
  Secondary: https://en.wikipedia.org/wiki/2026_FIFA_World_Cup
Last verified: 2026-05-24

Encodes the 16 R32 matchups (FIFA match numbers 73-88) as (slot_left, slot_right)
pairs and the downstream R16/QF/SF/F structure.

Slot notation
-------------
  "A1"    — winner of Group A
  "A2"    — runner-up of Group A
  "3RD_N" — N-th best third-placed team (1 = best, 8 = eighth best)

Third-place slot assignment
---------------------------
FIFA published 495 possible combinations in Annex C of the tournament
regulations, mapping each possible set of 8 qualifying third-placed groups
to specific R32 match slots.

v0 simplification (documented): we rank all 12 third-placed teams by
  points → goal difference → goals scored → drawing of lots
and take the top 8. We then assign them to slots 3RD_1..3RD_8 in rank
order. The eight "3RD_N" labels in WC2026_R32 therefore always receive
a team; however the exact group-origin-to-slot mapping from FIFA's Annex
C is NOT implemented (would require a 495-row lookup table). This is a
known simplification that does not affect bracket completeness or
probability-sum correctness, but may slightly over- or under-estimate
individual teams' expected paths compared to the exact FIFA routing.

TODO (v1): implement FIFA's Annex C combo-to-slot lookup table.
"""

from typing import Any


# ---------------------------------------------------------------------------
# R32 fixtures (FIFA match 73 → index 0, match 88 → index 15)
# Slot strings: "X1" = group X winner, "X2" = runner-up, "3RD_N" = N-th best 3rd.
# ---------------------------------------------------------------------------
#
# Match numbers and pairings from Wikipedia's 2026 FIFA World Cup knockout stage article:
#   Match 73  (index  0): A2  vs B2
#   Match 74  (index  1): E1  vs 3rd [A/B/C/D/F]
#   Match 75  (index  2): F1  vs C2
#   Match 76  (index  3): C1  vs F2
#   Match 77  (index  4): I1  vs 3rd [C/D/F/G/H]
#   Match 78  (index  5): E2  vs I2
#   Match 79  (index  6): A1  vs 3rd [C/E/F/H/I]
#   Match 80  (index  7): L1  vs 3rd [E/H/I/J/K]
#   Match 81  (index  8): D1  vs 3rd [B/E/F/I/J]
#   Match 82  (index  9): G1  vs 3rd [A/E/H/I/J]
#   Match 83  (index 10): K2  vs L2
#   Match 84  (index 11): H1  vs J2
#   Match 85  (index 12): B1  vs 3rd [E/F/G/I/J]
#   Match 86  (index 13): J1  vs H2
#   Match 87  (index 14): K1  vs 3rd [D/E/I/J/L]
#   Match 88  (index 15): D2  vs G2
#
# The 8 third-place slots 3RD_1..3RD_8 are assigned in rank order to
# the eight R32 matches that contain a 3RD slot.  Those matches are
# (in index order): 1, 4, 6, 7, 8, 9, 12, 14.
# The slots are assigned in ascending match-index order so:
#   3RD_1 → match 74 (index 1)   — group combo A/B/C/D/F
#   3RD_2 → match 77 (index 4)   — group combo C/D/F/G/H
#   3RD_3 → match 79 (index 6)   — group combo C/E/F/H/I
#   3RD_4 → match 80 (index 7)   — group combo E/H/I/J/K
#   3RD_5 → match 81 (index 8)   — group combo B/E/F/I/J
#   3RD_6 → match 82 (index 9)   — group combo A/E/H/I/J
#   3RD_7 → match 85 (index 12)  — group combo E/F/G/I/J
#   3RD_8 → match 87 (index 14)  — group combo D/E/I/J/L

SlotRef = str  # "A1" | "A2" | "3RD_1" | ... | "3RD_8"

WC2026_R32: list[tuple[SlotRef, SlotRef]] = [
    # index 0  — FIFA match 73
    ("A2", "B2"),
    # index 1  — FIFA match 74
    ("E1", "3RD_1"),
    # index 2  — FIFA match 75
    ("F1", "C2"),
    # index 3  — FIFA match 76
    ("C1", "F2"),
    # index 4  — FIFA match 77
    ("I1", "3RD_2"),
    # index 5  — FIFA match 78
    ("E2", "I2"),
    # index 6  — FIFA match 79
    ("A1", "3RD_3"),
    # index 7  — FIFA match 80
    ("L1", "3RD_4"),
    # index 8  — FIFA match 81
    ("D1", "3RD_5"),
    # index 9  — FIFA match 82
    ("G1", "3RD_6"),
    # index 10 — FIFA match 83
    ("K2", "L2"),
    # index 11 — FIFA match 84
    ("H1", "J2"),
    # index 12 — FIFA match 85
    ("B1", "3RD_7"),
    # index 13 — FIFA match 86
    ("J1", "H2"),
    # index 14 — FIFA match 87
    ("K1", "3RD_8"),
    # index 15 — FIFA match 88
    ("D2", "G2"),
]

# ---------------------------------------------------------------------------
# R16 — pairs of R32 match indices (0-based) whose winners play each other.
# FIFA matches 89-96.
#   Match 89 (R16 index 0): winner of index 1 (M74) vs winner of index 4 (M77)
#   Match 90 (R16 index 1): winner of index 0 (M73) vs winner of index 2 (M75)
#   Match 91 (R16 index 2): winner of index 3 (M76) vs winner of index 5 (M78)
#   Match 92 (R16 index 3): winner of index 6 (M79) vs winner of index 7 (M80)
#   Match 93 (R16 index 4): winner of index 10 (M83) vs winner of index 11 (M84)
#   Match 94 (R16 index 5): winner of index 8 (M81) vs winner of index 9 (M82)
#   Match 95 (R16 index 6): winner of index 13 (M86) vs winner of index 15 (M88)
#   Match 96 (R16 index 7): winner of index 12 (M85) vs winner of index 14 (M87)
# ---------------------------------------------------------------------------
WC2026_R16_FROM_R32: list[tuple[int, int]] = [
    (1, 4),    # R16-0: M74 winner vs M77 winner
    (0, 2),    # R16-1: M73 winner vs M75 winner
    (3, 5),    # R16-2: M76 winner vs M78 winner
    (6, 7),    # R16-3: M79 winner vs M80 winner
    (10, 11),  # R16-4: M83 winner vs M84 winner
    (8, 9),    # R16-5: M81 winner vs M82 winner
    (13, 15),  # R16-6: M86 winner vs M88 winner
    (12, 14),  # R16-7: M85 winner vs M87 winner
]

# QF — pairs of R16 match indices (0-based) whose winners play each other.
# FIFA matches 97-100.
#   Match 97 (QF-0): winner R16-0 vs winner R16-1  (M89 vs M90)
#   Match 98 (QF-1): winner R16-4 vs winner R16-5  (M93 vs M94)
#   Match 99 (QF-2): winner R16-2 vs winner R16-3  (M91 vs M92)
#   Match 100 (QF-3): winner R16-6 vs winner R16-7  (M95 vs M96)
WC2026_QF_FROM_R16: list[tuple[int, int]] = [
    (0, 1),  # QF-0
    (4, 5),  # QF-1
    (2, 3),  # QF-2
    (6, 7),  # QF-3
]

# SF — pairs of QF match indices (0-based) whose winners play each other.
# FIFA matches 101-102.
#   Match 101 (SF-0): winner QF-0 vs winner QF-1
#   Match 102 (SF-1): winner QF-2 vs winner QF-3
WC2026_SF_FROM_QF: list[tuple[int, int]] = [
    (0, 1),  # SF-0
    (2, 3),  # SF-1
]

# Final — pair of SF match indices.  SF-0 winner vs SF-1 winner.
WC2026_F_FROM_SF: tuple[int, int] = (0, 1)


# ---------------------------------------------------------------------------
# Third-place slot assignment
# ---------------------------------------------------------------------------

def assign_third_place_slots(ranked_third_teams: list) -> dict[str, Any]:
    """Return {"3RD_1": team, "3RD_2": team, ..., "3RD_8": team}.

    ranked_third_teams must be exactly 8 teams in descending rank order
    (best 3rd first, 8th-best last), ranked by points → GD → GF → lots.

    v0: order-based assignment — best 3rd goes to 3RD_1, etc.
    v1 (TODO): implement FIFA Annex C combo-to-slot lookup for exact routing.
    """
    if len(ranked_third_teams) != 8:
        raise ValueError(f"Expected 8 best-3rd teams; got {len(ranked_third_teams)}")
    return {f"3RD_{i + 1}": t for i, t in enumerate(ranked_third_teams)}
