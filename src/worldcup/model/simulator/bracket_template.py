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

v1: bipartite matching using per-slot eligibility constraints derived from
the FIFA bracket (equivalent to Annex C but computed at runtime).
"""

from typing import Any


# ---------------------------------------------------------------------------
# Third-place slot eligibility constraints
# ---------------------------------------------------------------------------
# Each R32 match that hosts a third-placed team has a set of eligible source
# groups. A 3rd-placed team from group X can only be placed in a slot whose
# eligibility set contains X. The constraint ensures no group-stage rematch
# (e.g. Match 74 is vs E1, so group E is excluded) plus additional FIFA
# routing rules.
#
# Slot label → (R32 match index, eligible groups)
# Ordered by ascending match index (same order as 3RD_1..3RD_8 in WC2026_R32).
SLOT_ELIGIBLE_GROUPS: list[tuple[str, int, frozenset[str]]] = [
    ("3RD_1", 1,  frozenset("ABCDF")),    # Match 74 vs E1
    ("3RD_2", 4,  frozenset("CDFGH")),    # Match 77 vs I1
    ("3RD_3", 6,  frozenset("CEFHI")),    # Match 79 vs A1
    ("3RD_4", 7,  frozenset("EHIJK")),    # Match 80 vs L1
    ("3RD_5", 8,  frozenset("BEFIJ")),    # Match 81 vs D1
    ("3RD_6", 9,  frozenset("AEHIJ")),    # Match 82 vs G1
    ("3RD_7", 12, frozenset("EFGIJ")),    # Match 85 vs B1
    ("3RD_8", 14, frozenset("DEIJL")),    # Match 87 vs K1
]

# ---------------------------------------------------------------------------
# R32 fixtures (FIFA match 73 → index 0, match 88 → index 15)
# Slot strings: "X1" = group X winner, "X2" = runner-up, "3RD_N" = N-th best 3rd.
# ---------------------------------------------------------------------------

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

def _match_thirds_to_slots(
    qualifying_groups: list[str],
    teams_by_group: dict[str, Any],
) -> dict[str, Any] | None:
    """Solve bipartite matching: assign 8 qualifying groups to 8 slots.

    Uses backtracking with most-constrained-first heuristic.
    Returns {"3RD_1": team, ...} or None if no valid assignment exists.
    """
    # Build slot → eligible qualifying groups (intersection with actual qualifiers)
    slots = []
    for slot_label, _match_idx, eligible in SLOT_ELIGIBLE_GROUPS:
        candidates = [g for g in qualifying_groups if g in eligible]
        slots.append((slot_label, candidates))

    # Sort by fewest candidates first (most-constrained-first)
    slots.sort(key=lambda x: len(x[1]))

    assignment: dict[str, str] = {}  # slot_label → group_letter
    used_groups: set[str] = set()

    def _backtrack(i: int) -> bool:
        if i == len(slots):
            return True
        slot_label, candidates = slots[i]
        for group in candidates:
            if group not in used_groups:
                used_groups.add(group)
                assignment[slot_label] = group
                if _backtrack(i + 1):
                    return True
                used_groups.discard(group)
                del assignment[slot_label]
        return False

    if not _backtrack(0):
        return None

    return {slot: teams_by_group[group] for slot, group in assignment.items()}


def assign_third_place_slots(
    ranked_third_teams: list,
    group_labels: list[str] | None = None,
) -> dict[str, Any]:
    """Return {"3RD_1": team, "3RD_2": team, ..., "3RD_8": team}.

    ranked_third_teams must be exactly 8 teams in descending rank order
    (best 3rd first, 8th-best last), ranked by points → GD → GF → lots.

    group_labels: parallel list of group letters (e.g. ["A", "C", "D", ...])
        indicating which group each team finished 3rd in. When provided,
        teams are assigned to slots using FIFA eligibility constraints
        (bipartite matching). When None, falls back to rank-order assignment.
    """
    if len(ranked_third_teams) != 8:
        raise ValueError(f"Expected 8 best-3rd teams; got {len(ranked_third_teams)}")

    if group_labels is not None:
        if len(group_labels) != 8:
            raise ValueError(f"Expected 8 group labels; got {len(group_labels)}")
        teams_by_group = dict(zip(group_labels, ranked_third_teams))
        result = _match_thirds_to_slots(group_labels, teams_by_group)
        if result is not None:
            return result
        # Fallback: if matching fails (should not happen with valid FIFA data),
        # use rank-order assignment.

    return {f"3RD_{i + 1}": t for i, t in enumerate(ranked_third_teams)}
