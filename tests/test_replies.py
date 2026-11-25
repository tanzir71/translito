from types import SimpleNamespace
from unittest.mock import Mock
import json
import pytest
from engines.replies import ReplyService, ReplyResult, parse_replies, phrasebook
from engines.mt_gemini import GeminiTranslator, PAID_RATE
from engines.provider import ProviderBinding
from engines.router import TranslatorRouter
from engines.usage import UsageLedger


def test_romanization_is_readable_ascii_and_latin_scripts_use_native_phrase():
    replies = parse_replies({"replies":[{"native":"شكرا","romanized":"Shukrán","meaning":"Thank you"},
        {"native":"Gracias","meaning":"Thank you"}]})
    assert replies[0].romanized == "Shukran" and replies[0].romanized.isascii()
    assert replies[1].spoken == "Gracias" and not replies[1].romanized


@pytest.mark.parametrize("language,target",[("es","en"),("en","ar"),("ar","en")])
def test_hidden_generation_costs_nothing_and_phrasebook_is_pair_agnostic(language,target):
    translator = SimpleNamespace(suggest_replies=Mock(side_effect=RuntimeError()))
    service = ReplyService(translator)
    assert not service.suggest(["private"],language,target,visible=False).replies
    translator.suggest_replies.assert_not_called()
    result = service.suggest(["Question?"],language,target)
    assert len(result.replies) == 3 and result.provider == "phrasebook"
    assert all(reply.romanized.isascii() for reply in result.replies)


def test_paid_reply_json_settles_tokens_and_zero_budget_blocks_transport(tmp_path):
    post = Mock(return_value={"candidates":[{"content":{"parts":[{"text":json.dumps({"replies":[
        {"native":"Si","romanized":"","meaning":"Yes"}]})}]}}],"usageMetadata":{"promptTokenCount":30,"totalTokenCount":40}})
    engine = GeminiTranslator(SimpleNamespace(get=lambda _:"fake-key"),http=SimpleNamespace(post=post))
    ledger = UsageLedger(tmp_path/"usage.json")
    binding = ProviderBinding(engine,enabled=True,tested=True,rate=PAID_RATE,monthly_cap=5)
    router = TranslatorRouter([binding],ledger=ledger,total_monthly_cap=0)
    assert ReplyService(router).suggest(["Question?"],"es").provider == "phrasebook"
    post.assert_not_called()
    router = TranslatorRouter([binding],ledger=ledger,total_monthly_cap=5)
    result = ReplyService(router).suggest(["Question?"],"es")
    assert result.provider == "gemini" and len(result.replies) == 2
    stats = ledger.snapshot()["providers"]["gemini"]
    assert stats["input_tokens"] == 30 and stats["output_tokens"] == 10
