from collections import Counter
import re
import unicodedata

import jiwer
from sacrebleu.metrics import CHRF


def normalize(text):
    """Preserve spelling/diacritics and scripts; ignore case and punctuation."""
    return " ".join("".join(
        " " if unicodedata.category(c).startswith("P") else c
        for c in unicodedata.normalize("NFC", text).casefold()
    ).split())


def latin_words(text):
    return re.findall(r"[a-z]+(?:[-'][a-z]+)*", text.casefold())


def repetition_loops(text):
    """Count maximal runs of >=4 identical consecutive 1..4-grams."""
    words = normalize(text).split()
    count, i = 0, 0
    while i < len(words):
        end = i
        for n in range(1, 5):
            pattern = words[i:i + n]
            if len(pattern) != n:
                break
            j = i + n
            while words[j:j + n] == pattern:
                j += n
            if (j - i) // n >= 4:
                end = max(end, j)
        if end > i:
            count += 1
            i = end
        else:
            i += 1
    return count


def score_clip(reference_source, reference_target, reference_tags, entries,
               transliterations=None, target_language="en", *, hypothesis_target=None):
    source = " ".join(e.get("source_text", "") for e in entries)
    target = " ".join(e.get("translated_text") or (
        e.get("source_text", "") if e.get("pass_through") else "") for e in entries)
    if hypothesis_target is not None:
        target = hypothesis_target
    ref, hyp = normalize(reference_source), normalize(source)
    expected = Counter(latin_words(reference_source))
    observed = Counter(latin_words(source))
    recalled = sum((expected & observed).values())
    term_count = sum(expected.values())
    tags = [e.get("language_tag", e.get("source_language", "")) for e in entries]
    tag_count = max(len(reference_tags), len(tags)) if reference_tags else 0
    correct_tags = sum(a == b for a, b in zip(reference_tags, tags))
    en_indices = [i for i, tag in enumerate(reference_tags) if tag == "en"]
    unnecessary = sum(bool(entries[i].get("mt_called")) for i in en_indices if i < len(entries))
    # Arbitrary back-transliteration cannot be inferred from a reference word.
    # Count only explicitly annotated spellings and disclose their coverage.
    covered = hits = 0
    for term, aliases in (transliterations or {}).items():
        occurrences = expected[term.casefold()]
        if occurrences:
            covered += occurrences
            for alias in aliases:
                hits += min(occurrences, len(re.findall(
                    r"(?<!\w)" + re.escape(alias) + r"(?!\w)", source)))
    reference_lines = reference_source.splitlines()
    aligned = bool(reference_tags) and len(reference_lines) == len(reference_tags) == len(entries)
    groups = {"group_metrics_aligned": aligned}
    for tag in ("en", "ar", "mix"):
        indices = [i for i, value in enumerate(reference_tags) if value == tag]
        group_ref = " ".join(reference_lines[i] for i in indices) if aligned else ""
        group_hyp = " ".join(entries[i].get("source_text", "") for i in indices) if aligned else ""
        groups[f"{tag}_wer"] = jiwer.wer(normalize(group_ref), normalize(group_hyp)) if aligned and indices else None
        if tag == "mix":
            wanted, actual = Counter(latin_words(group_ref)), Counter(latin_words(group_hyp))
            groups["mix_english_term_recall"] = sum((wanted & actual).values()) / sum(wanted.values()) if wanted else None
    return {
        "wer": jiwer.wer(ref, hyp),
        "cer": jiwer.cer(ref, hyp),
        "chrf": CHRF().sentence_score(target, [reference_target.strip()]).score,
        "tag_correct": correct_tags, "tag_count": tag_count,
        "tag_accuracy": correct_tags / tag_count if tag_count else None,
        "english_terms_recalled": recalled, "english_terms_total": term_count,
        "english_term_recall": recalled / term_count if term_count else None,
        "transliterated_terms": min(hits, covered), "annotated_terms_total": covered,
        "transliteration_rate": min(hits, covered) / covered if covered else None,
        "transliteration_annotation_coverage": covered / term_count if term_count else None,
        "unnecessary_mt_count": unnecessary if target_language == "en" else None,
        "english_utterances": len(en_indices) if target_language == "en" else None,
        "unnecessary_mt_rate": unnecessary / len(en_indices)
        if en_indices and target_language == "en" else None,
        "repetition_loops": repetition_loops(source) + repetition_loops(target),
        "reference_words": len(ref.split()), "reference_characters": len(ref), **groups,
    }
