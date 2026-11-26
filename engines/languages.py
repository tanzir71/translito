"""The app and website language catalog. Provider support is a separate policy."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Language:
    code: str
    english_name: str
    native_name: str
    script: str
    whisper_code: str
    bcp47: str
    site_locale: str | None
    slug: str | None
    fleurs_config: str
    iso6393: tuple[str, ...]
    default_variety: str = ""
    romanization_system: str = ""
    app_label: str = ""

    @property
    def rtl(self):
        return self.script == "arabic"

    @property
    def romanize_replies(self):
        return self.script != "latin"

    @property
    def priority(self):
        return self.site_locale is not None

    @property
    def base_code(self):
        return self.code.split("-")[0]

    @property
    def app_name(self):
        return self.app_label or self.english_name


CATALOG = (
    Language("en", "English", "English", "latin", "en", "en-US", "en", None, "en_us", ("eng",)),
    Language("de", "German", "Deutsch", "latin", "de", "de-DE", "de", "german", "de_de", ("deu", "ger")),
    Language("es", "Spanish", "Español (México)", "latin", "es", "es-MX", "es-mx", "spanish", "es_419", ("spa",), "es-MX"),
    Language("fr", "French", "Français", "latin", "fr", "fr-FR", "fr", "french", "fr_fr", ("fra", "fre")),
    Language("nl", "Dutch", "Nederlands", "latin", "nl", "nl-NL", "nl", "dutch", "nl_nl", ("nld", "dut")),
    Language("nb", "Norwegian", "Norsk", "latin", "no", "nb-NO", "nb", "norwegian", "nb_no", ("nor", "nob"), app_label="Norwegian (Bokmål)"),
    Language("pl", "Polish", "Polski", "latin", "pl", "pl-PL", "pl", "polish", "pl_pl", ("pol",)),
    Language("pt", "Portuguese", "Português (Brasil)", "latin", "pt", "pt-BR", "pt-br", "portuguese", "pt_br", ("por",), "pt-BR"),
    Language("sv", "Swedish", "Svenska", "latin", "sv", "sv-SE", "sv", "swedish", "sv_se", ("swe",)),
    Language("ar", "Arabic", "العربية", "arabic", "ar", "ar-SA", "ar", "arabic", "ar_eg", ("ara",), romanization_system="plain ASCII Arabic transliteration"),
    Language("zh-Hans", "Chinese, Simplified", "简体中文", "han", "zh", "zh-CN", "zh-cn", "chinese-simplified", "cmn_hans_cn", ("zho", "cmn", "chi"), romanization_system="Hanyu Pinyin without tone marks or tone numbers"),
    Language("zh-Hant", "Chinese, Traditional", "繁體中文", "han", "zh", "zh-TW", "zh-tw", "chinese-traditional", "cmn_hans_cn", ("zho", "cmn", "chi"), romanization_system="Hanyu Pinyin without tone marks or tone numbers"),
    Language("ja", "Japanese", "日本語", "japanese", "ja", "ja-JP", "ja", "japanese", "ja_jp", ("jpn",), romanization_system="Hepburn without macrons or accents"),
    Language("ko", "Korean", "한국어", "hangul", "ko", "ko-KR", "ko", "korean", "ko_kr", ("kor",), romanization_system="Revised Romanization without accents"),
    Language("it", "Italian", "Italiano", "latin", "it", "it-IT", None, None, "it_it", ("ita",)),
    Language("ru", "Russian", "Русский", "cyrillic", "ru", "ru-RU", None, None, "ru_ru", ("rus",), romanization_system="plain ASCII Russian transliteration"),
    Language("tr", "Turkish", "Türkçe", "latin", "tr", "tr-TR", None, None, "tr_tr", ("tur",)),
    Language("fa", "Persian", "فارسی", "arabic", "fa", "fa-IR", None, None, "fa_ir", ("fas", "per"), romanization_system="plain ASCII Persian transliteration"),
    Language("ur", "Urdu", "اردو", "arabic", "ur", "ur-PK", None, None, "ur_pk", ("urd",), romanization_system="plain ASCII Urdu transliteration"),
)

BY_CODE = {language.code: language for language in CATALOG}
CODES = frozenset(BY_CODE)
PRIORITY = tuple(language for language in CATALOG if language.priority)
LATIN_CODES = frozenset(code for language in CATALOG if language.script == "latin" for code in (language.code, language.whisper_code))
RTL_CODES = frozenset(language.code for language in CATALOG if language.rtl)

_ALIASES = {}
for _language in CATALOG:
    for _alias in (_language.code, _language.bcp47, _language.whisper_code, *_language.iso6393):
        _ALIASES.setdefault(_alias.casefold(), _language.code)


def canonical_code(value, *, preferred=None):
    value = str(value or "").replace("_", "-").casefold()
    selected = _ALIASES.get(value, _ALIASES.get(value.split("-")[0], value))
    if preferred in BY_CODE and BY_CODE[preferred].base_code == selected.split("-")[0]:
        return preferred
    return selected


def language(value):
    return BY_CODE.get(canonical_code(value))


def whisper_code(value):
    entry = language(value)
    return entry.whisper_code if entry else value


def gui_entries():
    return [(entry.app_name, entry.bcp47, entry.code) for entry in CATALOG]


def pair_default_variety(source, target):
    entry = language(target if canonical_code(source) == "en" else source)
    return entry.default_variety if entry else ""


def site_data():
    return [{**asdict(entry), "base_code": entry.base_code, "rtl": entry.rtl,
             "romanize_replies": entry.romanize_replies, "priority": entry.priority, "weight": index}
            for index, entry in enumerate(CATALOG, 1)]
