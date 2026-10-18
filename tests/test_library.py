"""The library: everything that already exists, searchable by everyone, with no-result searches counted."""
from test_scale import in_operation, post


def search(client, q="", **params):
    return client.get("/api/library", params={"q": q} | params).json()


def test_everything_in_the_catalog_is_listed_by_kind(client):
    everything = search(client)
    ids = [r["id"] for r in everything["results"]]
    assert {"SOL-001", "PRJ-011", "PRJ-005"} <= set(ids) and everything["count"] == len(ids)
    kinds = [r["kind"] for r in everything["results"]]
    assert kinds == sorted(kinds, key=list(everything["kinds"]).index)          # tools first, earlier pilots last


def test_search_finds_rewordings_and_ranks_the_best_match_first(client):
    results = search(client, "permits to work on paper")["results"]
    assert results[0]["id"] == "PRJ-011"
    assert "\u0002" in results[0]["title_marked"] or "\u0002" in results[0]["summary_marked"]
    assert search(client, "booking rooms for meetings")["results"][0]["id"] == "SOL-007"
    # "readings" shares a stem with "read access" in the spare parts how-to; how-to text isn't searched.
    assert "SOL-003" not in [r["id"] for r in search(client, "rack power readings")["results"]]


def test_kind_filter(client):
    pilots = search(client, kind="previous_pilot")["results"]
    assert pilots and all(r["kind"] == "previous_pilot" for r in pilots)


def test_search_words_are_never_treated_as_search_syntax(client):
    for tricky in ['" OR 1=1', "NEAR(permit work)", "permit*", "title:permit", "<script>alert(1)</script>"]:
        response = client.get("/api/library", params={"q": tricky})
        assert response.status_code == 200
    marked = search(client, "<b>permit</b>")["results"][0]["title_marked"]
    assert "<b>" not in marked                                                    # only marks, no HTML from the query


def test_published_lessons_appear_with_team_only_links(client):
    sid = in_operation(client)
    post(client, sid, "lessons/draft")
    post(client, sid, "lessons/publish", title="Automated weekly energy report",
         summary="Energy reports now refresh automatically from the source tools.", keywords=["energy reports"])
    employee = search(client, "energy reports")["results"][0]
    assert employee["lesson"] and employee["request"] is None and employee["source"] == "Innovation Hub lesson"
    team = search(client, "energy reports", team=True)["results"][0]
    assert team["request"] == sid


def test_searches_with_no_result_are_counted_for_the_team(client):
    search(client, "drone inspections of the roof")
    search(client, "Drone inspections of the roof")                              # listed once
    search(client, "permit to work")
    search(client)                                                               # browsing isn't a search
    metrics = client.get("/api/metrics").json()
    assert metrics["library_searches"] == 3 and metrics["library_found_share"] == 0.33
    assert metrics["library_no_results"] == ["drone inspections of the roof"]
