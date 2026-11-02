"""Hardware probes. Unsupported and gated models are reported, never guessed."""
import json
from pathlib import Path
import time

from tools.eval.runtime import PeakMemory


def load_recognizer(name, allow_downloads):
    import psutil
    threads = max(2, (psutil.cpu_count(logical=False) or 2) - 1)
    if name in {"turbo-int8", "base-lid"}:
        from faster_whisper import WhisperModel
        model = WhisperModel("large-v3-turbo" if name == "turbo-int8" else "base",
                             device="cpu", compute_type="int8", cpu_threads=threads,
                             local_files_only=not allow_downloads)

        def decode(audio):
            if name == "base-lid":
                # This is an encoder/LID pass, not English/Arabic transcription.
                return model.detect_language(audio)
            segments, _ = model.transcribe(audio, language=None, beam_size=3,
                                           condition_on_previous_text=False)
            return " ".join(s.text for s in segments)

        return decode
    if name not in {"cohere-fp32", "cohere-bf16", "cohere-int8"}:
        raise ValueError(f"Unknown recognizer: {name}")
    import torch
    from transformers import AutoProcessor, CohereAsrForConditionalGeneration
    repo = "CohereLabs/cohere-transcribe-arabic-07-2026"
    kwargs = {"local_files_only": not allow_downloads, "token": False}
    # Credential Manager support is integrated in P2. This P0 probe never reads
    # a token from config, environment, chat or the Hugging Face disk token file.
    processor = AutoProcessor.from_pretrained(repo, **kwargs)
    dtype = torch.bfloat16 if name == "cohere-bf16" else torch.float32
    model = CohereAsrForConditionalGeneration.from_pretrained(repo, torch_dtype=dtype, **kwargs)
    model.eval()
    torch.set_num_threads(threads)
    if name == "cohere-int8":
        model = torch.ao.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)

    def decode(audio):
        inputs = processor(audio=audio, sampling_rate=16000, return_tensors="pt", language="ar")
        inputs = inputs.to("cpu", dtype=dtype)
        with torch.inference_mode():
            output = model.generate(**inputs, max_new_tokens=256)
        return processor.decode(output, skip_special_tokens=True)

    return decode


def benchmark(args):
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
    result = {"recognizer": args.recognizers, "audio_seconds": seconds}
    with PeakMemory() as memory:
        try:
            start = time.perf_counter()
            decode = load_recognizer(args.recognizers, args.allow_downloads)
            result["load_s"] = time.perf_counter() - start
            times = []
            for audio in clips:
                start = time.perf_counter()
                decode(audio)
                times.append(time.perf_counter() - start)
            elapsed = sum(times)
            result.update(status="measured", decode_s=elapsed, rtf=elapsed / seconds,
                          decode_times_s=times, live_headroom_ok=elapsed / seconds < 0.7)
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            # Exception messages from download clients can include auth details.
            # Preserve the failure class without printing URLs/headers/secrets.
            result.update(status="unavailable", error_type=type(exc).__name__,
                          reason="Install the required runtime and cache/authorize this model, then rerun.")
    result["peak_rss_bytes"] = memory.peak
    return result


def write_bench_report(output, results, meta):
    lines = ["# Local hardware benchmark", "", f"Commit: `{meta['git_commit']}`", "",
             "| Recognizer | Status | RTF | Peak RAM (GiB) | Load (s) |",
             "|---|---|---:|---:|---:|"]
    for result in results:
        rtf = f"{result['rtf']:.3f}" if "rtf" in result else "n/a"
        load = f"{result['load_s']:.2f}" if "load_s" in result else "n/a"
        lines.append(f"| {result['recognizer']} | {result['status']} | {rtf} | "
                     f"{result['peak_rss_bytes'] / 2**30:.2f} | {load} |")
    lines.extend(["", "RTF = decode time / audio time; lower is faster. Model loading is excluded.",
                  "Unavailable is not a passing speed or quality measurement.",
                  "base-lid measures language detection only; its RTF is not transcription speed.",
                  "The 0.7 live-headroom threshold is a speed gate, not an accuracy gate.", ""])
    (output / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    (output / "run.json").write_text(json.dumps({"metadata": meta, "benchmarks": results},
                                               indent=2), encoding="utf-8")
