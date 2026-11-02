"""Hardware probes. Unsupported and gated models are reported, never guessed."""
from contextlib import nullcontext
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
from typing import Callable
from unittest.mock import patch

from tools.eval.runtime import PeakMemory, block_network


RECOGNIZERS = ("cohere-fp32", "cohere-bf16", "cohere-int8", "turbo-int8", "small-int8", "base-lid", "codeswitch-int8")
DEFAULT_RECOGNIZERS = ",".join(RECOGNIZERS[:-1])


@dataclass
class RecognizerProbe:
    decode: Callable
    kind: str
    info: dict

    def __call__(self, audio):
        return self.decode(audio)


def load_recognizer(name, allow_downloads, *, language="ar", cohere_terms_accepted=False):
    if name not in RECOGNIZERS:
        raise ValueError("Unknown recognizer; use a supported benchmark name")
    if allow_downloads:
        from native_tls import configure_native_tls
        configure_native_tls()
    from model_loading import FastWhisperASR, physical_cpu_threads, fast_whisper_repo, _local_fast_whisper_model
    threads = physical_cpu_threads()
    if name in {"turbo-int8", "small-int8", "base-lid"}:
        from faster_whisper import WhisperModel
        alias = {"turbo-int8": "large-v3-turbo", "small-int8": "small", "base-lid": "base"}[name]
        folder = _local_fast_whisper_model(alias)
        overridden = folder is not None
        if folder is None:
            from huggingface_hub import snapshot_download
            # No implicit HF disk-token login, including on cache lookups.
            folder = snapshot_download(fast_whisper_repo(alias), token=False, local_files_only=not allow_downloads,
                                       allow_patterns=["model.bin", "config.json", "tokenizer.json", "vocabulary.*", "preprocessor_config.json"])
        model = WhisperModel(folder, device="cpu", compute_type="int8", cpu_threads=threads, local_files_only=True)
        info = {"model": fast_whisper_repo(alias), "precision": "int8", "cpu_threads": threads,
                "cache_override": overridden, "adapter": "PairLanguageDetector" if name == "base-lid" else "FastWhisperASR"}
        if name == "base-lid":
            from engines.lid import PairLanguageDetector
            detector = PairLanguageDetector(model, "ar" if language == "en" else language)
            return RecognizerProbe(detector.detect, "lid", info)
        recognizer = FastWhisperASR(model, beam_size=3)
        info["beam_size"] = 3
        return RecognizerProbe(lambda audio: recognizer.transcribe_result(audio, language=language), "asr", info)
    if name == "codeswitch-int8":
        if language not in {"ar", "en"}:
            raise ValueError("The Arabic/English fallback probe requires --source ar or en")
        from engines.asr_codeswitch import (CODESWITCH_REPO, prepared_codeswitch_directory,
                                            prepare_codeswitch_model, load_cached_codeswitch)
        if prepared_codeswitch_directory() is None and allow_downloads:
            prepare_codeswitch_model()
        recognizer = load_cached_codeswitch(device="cpu")
        return RecognizerProbe(lambda audio: recognizer.transcribe_result(audio, language=language), "asr",
                               {"model": CODESWITCH_REPO, "precision": "int8", "cpu_threads": threads,
                                "adapter": "FastWhisperASR", "beam_size": recognizer.beam_size})
    if language not in {"ar", "en"}:
        raise ValueError("Cohere Arabic probes require --source ar or en")
    from app_config import load_cohere_cache_dir
    from audio_processing import SpeechActivityDetector
    from engines.asr_cohere_local import CohereAccessRequired, CohereLocalRecognizer, MODEL_ID
    credentials = None
    download = allow_downloads and cohere_terms_accepted
    if download:
        from engines.secrets import CredentialStore
        key = CredentialStore().get("huggingface")
        if not isinstance(key, str) or not key.strip():
            raise CohereAccessRequired("Save a read token in the app's Cohere setup before authorizing model downloads.")
        credentials = SimpleNamespace(get=lambda provider: key if provider == "huggingface" else None)
    precision = {"cohere-fp32": "float32", "cohere-bf16": "bfloat16", "cohere-int8": "int8"}[name]
    import torch
    # Silero's first import sets global Torch threads to one. Apply the
    # requested probe policy after creating VAD, including direct callers.
    detector = SpeechActivityDetector()
    torch.set_num_threads(threads)
    cache = load_cohere_cache_dir()
    recognizer = CohereLocalRecognizer(offline_only=not download, dtype=precision, device="cpu", cache_dir=cache,
                                      credentials=credentials, detector=detector)
    recognizer.load()
    return RecognizerProbe(lambda audio: recognizer.transcribe(audio, 16000, hint_language=language), "asr",
                           {"model": MODEL_ID, "precision": precision, "cpu_threads": torch.get_num_threads(),
                            "cache_override": cache is not None, "gated_download_authorized": bool(download),
                            "adapter": "CohereLocalRecognizer"})


def segment_clips(clips, *, detector_factory=None):
    from audio_processing import AudioChunkProcessor, SpeechActivityDetector
    detector_factory = detector_factory or SpeechActivityDetector
    segments, vad_load, vad_compute = [], 0.0, 0.0
    for index, samples in enumerate(clips):
        started = time.perf_counter()
        detector = detector_factory()  # Each clip starts a fresh VAD session.
        vad_load += time.perf_counter() - started
        processor = AudioChunkProcessor(input_sample_rate=16000, speech_detector=detector)
        started = time.perf_counter()
        chunks = []
        for offset in range(0, len(samples), 1600):
            chunks.extend(processor.append(samples[offset:offset + 1600], 16000))
        chunks.extend(processor.flush())
        vad_compute += time.perf_counter() - started
        segments.extend((index, chunk.samples) for chunk in chunks if chunk.kind == "audio")
    return segments, vad_load, vad_compute


def benchmark(args, *, recognizer_loader=None, detector_factory=None):
    from tools.eval.run_eval import read_audio
    if args.manifest:
        manifest = Path(args.manifest).resolve()
        files = [Path(p) if Path(p).is_absolute() else manifest.parent / p
                 for p in json.loads(manifest.read_text(encoding="utf-8-sig"))["clips"]]
    else:
        files = sorted(Path(args.input).rglob("*.wav"))
    if not files:
        raise ValueError("No WAV clips for hardware benchmark")
    # Use all supplied audio, not a repeated zero/tone approximation.
    clips = [read_audio(path)[0] for path in files]
    seconds = sum(len(x) for x in clips) / 16000
    result = {"recognizer": args.recognizers, "audio_seconds": seconds,
              "language": args.source, "protocol": "desktop-vad-and-local-adapter-v2",
              "live_headroom_ok": None, "asr_speed_gate_passed": False,
              "inputs": [{"clip": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in files]}
    environment = {"OFFLINE_ONLY": "0" if args.allow_downloads else "1",
                   "HF_HUB_OFFLINE": "0" if args.allow_downloads else "1",
                   "TRANSFORMERS_OFFLINE": "0" if args.allow_downloads else "1"}
    with PeakMemory() as memory:
        try:
            with patch.dict(os.environ, environment), nullcontext() if args.allow_downloads else block_network():
                segments, vad_load, vad_compute = segment_clips(clips, detector_factory=detector_factory)
                speech_seconds = sum(len(audio) for _, audio in segments) / 16000
                result.update(segment_count=len(segments), segmented_audio_seconds=speech_seconds,
                              vad_load_s=vad_load, vad_compute_s=vad_compute)
                if not segments:
                    result.update(status="no_speech", live_headroom_ok=None, asr_speed_gate_passed=False)
                else:
                    start = time.perf_counter()
                    probe = (recognizer_loader or load_recognizer)(args.recognizers, args.allow_downloads, language=args.source,
                        cohere_terms_accepted=getattr(args, "cohere_terms_accepted", False))
                    result.update(load_s=time.perf_counter() - start, measurement=probe.kind, engine=probe.info)
                    predictions, times, empty = [], [], 0
                    result.update(predictions=predictions, decode_times_s=times)
                    for index, audio in segments:
                        start = time.perf_counter()
                        decoded = probe(audio)
                        duration = time.perf_counter() - start
                        times.append(duration)
                        row = {"clip": files[index].name, "audio_seconds": len(audio) / 16000, "decode_s": duration}
                        if probe.kind == "asr":
                            if not isinstance(getattr(decoded, "text", None), str):
                                raise ValueError("The local recognizer did not return transcript text")
                            row.update(text=decoded.text, language=decoded.language)
                            empty += not bool(decoded.text.strip())
                        else:
                            row.update(language=decoded.language, probability=decoded.probability)
                        predictions.append(row)
                    elapsed = sum(times)
                    result.update(status="measured", decode_s=elapsed, rtf=elapsed / seconds,
                        segment_rtf=elapsed / speech_seconds, decode_times_s=times, predictions=predictions,
                        empty_output_segments=empty, live_headroom_ok=elapsed / speech_seconds < .7,
                        asr_speed_gate_passed=probe.kind == "asr" and empty == 0 and elapsed / speech_seconds < .7)
        except Exception as exc:
            # Exception messages from download clients can include auth details.
            # Preserve the failure class without printing URLs/headers/secrets.
            result.update(status="unavailable", error_type=type(exc).__name__,
                          reason="Install the required runtime and cache/authorize this model, then rerun.")
    result["peak_rss_bytes"] = memory.peak
    return result


def write_bench_report(output, results, meta):
    lines = ["# Local hardware benchmark", "", f"Commit: `{meta['git_commit']}`", "",
             "| Recognizer | Status | Decode/input RTF | Decode/segmented RTF | Peak RAM (GiB) | Load (s) |",
             "|---|---|---:|---:|---:|---:|"]
    for result in results:
        rtf = f"{result['rtf']:.3f}" if "rtf" in result else "n/a"
        load = f"{result['load_s']:.2f}" if "load_s" in result else "n/a"
        segment_rtf = f"{result['segment_rtf']:.3f}" if "segment_rtf" in result else "n/a"
        lines.append(f"| {result['recognizer']} | {result['status']} | {rtf} | {segment_rtf} | "
                     f"{result['peak_rss_bytes'] / 2**30:.2f} | {load} |")
    lines.extend(["", "Decoder timing uses the desktop local adapters on VAD-positive utterances of at most 15 seconds.",
                  "RTF = decode time / audio time; lower is faster. Segmented RTF prevents silence diluting the speed gate.",
                  "Model/VAD loading and segmentation compute are recorded separately, outside decoder timing.",
                  "These probes force --source; the conversation LID and MT stages are not included in ASR timing.",
                  "Unavailable is not a passing speed or quality measurement.",
                  "VAD-negative inputs are no_speech; empty transcriptions cannot qualify an ASR recommendation.",
                  "base-lid measures language detection only; its RTF is not transcription speed.",
                  "The 0.7 segmented-audio headroom threshold is a component speed gate, not end-to-end latency or accuracy acceptance.", ""])
    (output / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    (output / "run.json").write_text(json.dumps({"metadata": meta, "benchmarks": results},
                                               indent=2), encoding="utf-8")
