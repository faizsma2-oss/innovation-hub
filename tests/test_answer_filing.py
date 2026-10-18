"""An answer is filed under the field it's actually about, when it clearly doesn't answer the question asked."""
from backend.intake import workflow
from conftest import Chat
from test_claude_brain import use_claude  # noqa: F401  (fixture)

FIELDS = ["current_process", "frequency", "people_affected", "impact", "tried_already"]


def step(next_field, question, **extracted):
    return {"extracted": {f: extracted.get(f, "") for f in FIELDS}, "next_field": next_field, "question": question}


FIRST = "Every night shift we write cold room temperatures on paper, then type them into Excel. About 2 hours a shift."
TEAM = "The operations team at two sites is affected, about 12 technicians."


def test_the_live_run_case_is_refiled_to_who_is_affected(client, use_claude):
    use_claude(
        step("tried_already", "Have you tried anything to make this easier?",
             current_process="Every night shift we write cold room temperatures on paper, then type them into Excel.",
             frequency="Every night shift", people_affected="night shift", impact="About 2 hours a shift."),
        step("done", "", people_affected="The operations team at two sites is affected, about 12 technicians."),
        {"summary": "Night-shift cold room temperatures are written on paper and retyped into Excel.", "open_questions": []})
    chat = Chat(client)
    chat.say(FIRST)
    reply = chat.say(TEAM)
    draft = reply["draft"]
    assert draft["tried_already"] is None                                     # the question stays open
    assert draft["people_affected"] == "night shift; The operations team at two sites is affected, about 12 technicians."
    if reply["stage"] != "closed":
        chat.click("submit")
    notes = chat.submission()["brief"]["notes"]
    assert any("about who is affected, so it was filed there" in n for n in notes)


def test_a_passing_mention_stays_where_it_was_asked(client, use_claude):
    answer = "We tried a spreadsheet macro last year, it broke every week."
    use_claude(step("tried_already", "Have you tried anything?", current_process="We write temperatures on paper."),
               step("done", "", frequency="every week"))
    chat = Chat(client)
    chat.say("We write cold room temperatures on paper and retype them.")
    draft = chat.say(answer)["draft"]
    assert draft["tried_already"] == answer and draft["frequency"] == "every week"


def test_an_answer_to_the_question_is_filed_there_even_if_it_mentions_other_things(client, use_claude):
    answer = "The 12 technicians on night shift, at both sites."
    use_claude(step("people_affected", "Who does it affect?", current_process="We retype readings."),
               step("done", "", people_affected=answer, frequency="night shift"))
    chat = Chat(client)
    chat.say("We retype cold room readings from paper into Excel.")
    assert chat.say(answer)["draft"]["people_affected"] == answer


def test_refiled_text_must_be_the_employees_own_words():
    # An extract with a number the answer doesn't contain isn't trusted, so nothing is refiled.
    assert workflow.refiled_fields("tried_already", {"people_affected": "About 40 technicians at two sites"},
                                   "The operations team at two sites, about 12 technicians.") == {}
    assert workflow.refiled_fields("tried_already", {"people_affected": "The operations team at two sites, about 12 technicians"},
                                   "The operations team at two sites, about 12 technicians.") \
        == {"people_affected": "The operations team at two sites, about 12 technicians"}
