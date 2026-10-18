"""Arabic in the intake chat: translated in for the rules, translated out for the employee, original kept,
safety checked on the Arabic itself, and a clear fallback when the translator is off. Fake Claude: no cost."""
import json
from types import SimpleNamespace

import pytest

from backend.intake import language
from conftest import Chat

REPORT = "كل أسبوع ندمج تقارير الطاقة من ثلاثة أنظمة يدويًا، وهذا يأخذ ٦ ساعات."
REPORT_EN = "Every week we manually combine energy reports from three systems, and this takes 6 hours."


class FakeTranslator:
    def __init__(self, english=REPORT_EN):
        self.english, self.calls = english, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **request):
        payload = json.loads(request["messages"][0]["content"])
        if "labels" in payload:
            reply = {"message": "[AR] " + payload["message"], "labels": ["[AR] " + l for l in payload["labels"]]}
        else:
            reply = {"english": self.english}
        self.calls.append(reply)
        return SimpleNamespace(model="claude-opus-5-5", stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=300, output_tokens=120,
                                                     cache_creation_input_tokens=0, cache_read_input_tokens=0),
                               content=[SimpleNamespace(type="text", text=json.dumps(reply))])


@pytest.fixture
def translator(monkeypatch):
    def install(english=REPORT_EN):
        fake = FakeTranslator(english)
        monkeypatch.setattr(language, "available", lambda: True)
        monkeypatch.setattr(language, "client", lambda given=None: fake)
        return fake
    return install


def test_detects_arabic_and_reads_arabic_digits():
    assert language.is_arabic(REPORT) and language.is_arabic("الـ VPN لا يعمل منذ الصباح")
    assert not language.is_arabic("The VPN isn't working, شكرا")
    assert language.western_digits("٦ ساعات و ١٢٫٥") == "6 ساعات و 12.5"
    assert not language.numbers_added(REPORT_EN, REPORT)
    assert language.numbers_added("This takes 8 hours every week", REPORT)


def test_arabic_is_translated_in_for_the_rules_and_out_for_the_employee(client, translator):
    fake = translator()
    chat = Chat(client)
    reply = chat.say(REPORT)
    assert reply["message"].startswith("[AR] ") and all(o["label"].startswith("[AR] ") for o in reply["options"])
    assert reply["draft"]["description"] == REPORT_EN                    # the rules worked on the English
    chat.dont_know_until_done()
    chat.click("submit")
    record = chat.submission()
    assert record["route"] == "process_owner_innovation"                 # routed by the English rules
    assert any(n.startswith("Original (Arabic): «كل أسبوع") for n in record["brief"]["notes"])
    assert len(fake.calls) >= 2


def test_translation_that_adds_a_number_is_flagged(client, translator):
    translator(english="Every week we combine energy reports from three systems, it takes 9 hours.")
    chat = Chat(client)
    chat.say(REPORT)
    chat.dont_know_until_done()
    chat.click("submit")
    record = chat.submission()
    assert "translation_numbers" in record["brief"]["flags"]


def test_arabic_safety_words_are_caught_even_without_the_translator(client, monkeypatch):
    monkeypatch.setattr(language, "available", lambda: False)
    reply = Chat(client).say("يوجد دخان في قاعة البيانات رقم ٢")
    assert reply["stage"] == "safety_check"
    assert "قناة الحوادث" in reply["message"] and "incident channel" in reply["message"]
    assert any("نعم" in o["label"] for o in reply["options"])


def test_without_the_translator_the_chat_says_so_and_a_person_reads_the_original(client, monkeypatch):
    monkeypatch.setattr(language, "available", lambda: False)
    chat = Chat(client)
    reply = chat.say(REPORT)
    assert reply["message"].startswith(language.NO_TRANSLATOR)
    chat.click("submit")
    record = chat.submission()
    assert record["description"] == REPORT and record["route"] == "human_triage"
    assert "untranslated" in record["brief"]["flags"]


def test_english_conversations_are_untouched(client, translator):
    fake = translator()
    reply = Chat(client).say("Every week we manually combine reports from several systems.")
    assert not reply["message"].startswith("[AR]") and fake.calls == []
