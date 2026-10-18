"""Matching what already exists: a labelled set of rewordings that should and shouldn't match.
Before full-text search (exact phrases, unweighted words) this set scored 10/16 and 5/6."""
import pytest

from backend import db
from backend.intake import search

CATALOG = [  # (employee text, expected catalog id or None)
    ("Paper handover notes between shifts get lost", "SOL-001"),
    ("When shifts are changing, notes about open jobs get lost", "SOL-001"),
    ("Visitors wait at the gate because their badges aren't printed", "SOL-002"),
    ("We keep running out of spare parts and nobody can see the stock", "SOL-003"),
    ("Nobody knows the level of stock for each part", "SOL-003"),
    ("Receipts for expenses are submitted on paper", "SOL-004"),
    ("Our training records are scattered across spreadsheets", "SOL-005"),
    ("Records of who completed which training are in different places", "SOL-005"),
    ("Booking a room for team meetings is hard", "SOL-007"),
    ("Paper permits slow down maintenance work", "PRJ-011"),
    ("Permits to work are still filled in on paper", "PRJ-011"),
    ("Chiller faults are always found late", "PRJ-005"),
    ("The kettle in the kitchen is broken", None),
    ("The coffee machine in the break room is broken", None),
    ("Our handbook for new starters is out of date", None),
    ("Stocking the kitchen shelves takes too long", None),
]
# (employee text, expected seeded request or None)
SIMILAR = [
    ("Several sites repeat the same inspection paperwork: handwritten inspection notes are copied into shared reports by hand.", "SUB-0001"),
    ("Writing up inspection reports from handwritten notes takes hours", "SUB-0001"),
    ("Which version of a procedure is current? Documents sit in several folders and we ask around", "SUB-0002"),
    ("Purchase requests come in with missing details and we chase people for them", "SUB-0003"),
    ("The team spends a lot of time every week on emails", None),
    ("Night shift team reports that the kitchen is too cold", None),
]


@pytest.mark.parametrize("text, expected", CATALOG)
def test_tools_and_lessons_match_rewordings_but_not_unrelated_text(client, text, expected):
    with db.connect() as conn:
        found = search.find_solution(conn, text)
    assert (found and found["id"]) == expected


@pytest.mark.parametrize("text, expected", SIMILAR)
def test_similar_requests_match_on_telling_words_not_common_ones(client, text, expected):
    with db.connect() as conn:
        found = search.find_similar_submission(conn, text)
    assert (found and found["id"]) == expected


def test_stems_ignore_word_form_and_filler_words():
    found = search.stems({"a": "Combining the energy reports", "b": "energy report combined every week"})
    assert found["a"] == found["b"] == {"combin", "energi", "report"}      # "every" and "week" are ignored
