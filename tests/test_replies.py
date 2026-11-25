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


def test_reply_shortcut_copies_romanization_without_speak_output():
    from reply_ui import ReplyController
    from engines.replies import Reply
    root = SimpleNamespace(clipboard_clear=Mock(),clipboard_append=Mock())
    controller = ReplyController.__new__(ReplyController)
    controller.app = SimpleNamespace(root=root,speak_output_var=SimpleNamespace(get=lambda:""))
    controller.replies, controller.status = (Reply("شكرا","Shukran","Thank you"),), Mock()
    controller.somewhere_visible = lambda:True
    controller.say(0)
    root.clipboard_append.assert_called_once_with("Shukran")


def test_reply_bindings_are_recordable_persisted_and_registered_with_fake_keyboard(tmp_path,monkeypatch):
    import sys
    from app_config import DEFAULT_HOTKEYS,save_hotkey_config,load_hotkey_config
    from hotkeys import GlobalHotkeyManager
    bindings = dict(DEFAULT_HOTKEYS,reply_1="ctrl+shift+7")
    path = tmp_path/"config.ini"
    save_hotkey_config(path,bindings)
    assert load_hotkey_config(path)["reply_1"] == "ctrl+shift+7"
    keyboard = SimpleNamespace(add_hotkey=Mock(return_value="registered"),remove_hotkey=Mock())
    monkeypatch.setitem(sys.modules,"keyboard",keyboard)
    manager = GlobalHotkeyManager({key:Mock() for key in bindings})
    manager.register(bindings)
    assert keyboard.add_hotkey.call_count == len(bindings)
    assert any(call.args[0] == "ctrl+shift+7" for call in keyboard.add_hotkey.call_args_list)
