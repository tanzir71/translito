#!/usr/bin/env python3
"""Evaluate the desktop pipeline. Run with --help for the sidecar contract."""
import argparse
from contextlib import nullcontext
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np

from engines.usage import LOCAL_RATE, estimate_cost
from tools.eval.metrics import score_clip
from tools.eval.runtime import DesktopRuntime, PeakMemory, block_network
from tools.eval.streaming_runner import PROFILES as STREAMING_PROFILES, PaidPolicy, StreamingRuntime


def read_audio(path):
    # PyAV is already a faster-whisper dependency. Unlike wave, it supports
    # IEEE-float WAV and multichannel input as well as integer PCM.
    import av
    frames = []
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="fltp", layout="mono", rate=16000)
        for frame in container.decode(stream):
            frames.extend(x.to_ndarray().reshape(-1) for x in resampler.resample(frame))
        frames.extend(x.to_ndarray().reshape(-1) for x in resampler.resample(None))
    if not frames:
        raise ValueError(f"Empty audio file: {path.name}")
    samples = np.concatenate(frames).astype(np.float32)
    if not np.isfinite(samples).all():
        raise ValueError(f"Non-finite audio samples: {path.name}")
    return samples, 16000


def find_clips(folder=None, manifest=None):
    if manifest:
        manifest = Path(manifest).resolve()
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        paths = [Path(x) if Path(x).is_absolute() else manifest.parent / x
                 for x in data["clips"]]
    else:
        paths = sorted(Path(folder).rglob("*.wav"))
    if not paths:
        raise ValueError("No WAV clips found")
    clips = []
    for path in paths:
        if not path.is_file():
            raise ValueError(f"Audio file does not exist: {path}")
        prefix = path.with_suffix("")
        src = Path(str(prefix) + ".ref.src.txt")
        tgt = Path(str(prefix) + ".ref.tgt.txt")
        if not src.is_file() or not tgt.is_file():
            raise ValueError(f"Missing reference sidecars for {path.name}")
        tag_file = Path(str(prefix) + ".ref.tag.txt")
        tags = tag_file.read_text(encoding="utf-8-sig").split() if tag_file.exists() else []
        source = src.read_text(encoding="utf-8-sig").strip()
        target = tgt.read_text(encoding="utf-8-sig").strip()
        if tags and len(tags) != len(source.splitlines()):
            raise ValueError(f"{tag_file.name}: provide one tag per source reference line")
        terms_file = Path(str(prefix) + ".ref.terms.json")
        terms = json.loads(terms_file.read_text(encoding="utf-8-sig")) if terms_file.exists() else {}
        if not isinstance(terms, dict) or any(not isinstance(v, list) for v in terms.values()):
            raise ValueError(f"Invalid term annotations for {path.name}")
        clips.append({"path": path.resolve(), "source": source, "target": target,
                      "tags": tags, "terms": terms})
    return clips


def percentile(values, percentile):
    return float(np.percentile(values, percentile)) if values else None


def evaluate_profile(clips, profile, args, runtime_factory=DesktopRuntime):
    with PeakMemory() as memory:
        load_started = time.perf_counter()
        if profile in STREAMING_PROFILES:
            runtime = StreamingRuntime(profile, target=args.target,
                policy=PaidPolicy.read(args.paid_policy, profile, allow_cloud=args.allow_cloud, allow_paid=args.allow_paid),
                monthly_path=args.paid_usage, run_path=args.paid_run_usage,
                allow_cloud_mt=args.stream_mt == "free_cloud")
        else:
            runtime = runtime_factory(
                profile, source=args.source, target=args.target,
                whisper_model=args.whisper_model, allow_network=args.allow_downloads, allow_cloud=args.allow_cloud,
                legacy_fixed_window=args.legacy_fixed_window,
            )
        load_seconds = time.perf_counter() - load_started
        rows, predictions = [], []
        for index, clip in enumerate(clips):
            samples, rate = read_audio(clip["path"])
            result = runtime.evaluate(samples, rate)
            load_seconds += result.get("setup_s", 0)
            tags = clip["tags"] if result.get("utterance_tag_metrics", True) else []
            metrics = score_clip(clip["source"], clip["target"], tags,
                                 result["entries"], clip["terms"], args.target)
            latency = result["processing_latencies_s"]
            end_latency = result["speech_end_latencies_s"]
            row = {"profile": profile, "clip": clip["path"].name,
                   "audio_sha256": hashlib.sha256(clip["path"].read_bytes()).hexdigest(),
                   "audio_seconds": len(samples) / rate, "elapsed_s": result["elapsed_s"],
                   "rtf": result["elapsed_s"] / (len(samples) / rate),
                   "segments": result["segment_count"], "rows": len(result["entries"]),
                   "processing_p50_s": percentile(latency, 50),
                   "processing_p95_s": percentile(latency, 95),
                   "speech_end_p50_s": percentile(end_latency, 50),
                   "speech_end_p95_s": percentile(end_latency, 95),
                   "mt_characters": result["mt_characters"],
                   "mt_requests": result["mt_requests"],
                   "estimated_cost_usd": result.get("estimated_cost_usd", str(estimate_cost(LOCAL_RATE))),
                   "cost_status": result.get("cost_status", "No paid API cost; free-tier quota accounting is separate"),
                   "error_count": len(result["errors"]), **metrics}
            rows.append(row)
            predictions.append({"clip": str(clip["path"]), "profile": profile,
                                "reference_source": clip["source"],
                                "reference_target": clip["target"], **result})
            print(f"{profile}: {index + 1}/{len(clips)} {clip['path'].name}: "
                  f"WER {metrics['wer']:.3f}, chrF {metrics['chrf']:.1f}", flush=True)
    return {"profile": profile, "rows": rows, "predictions": predictions,
            "model_load_s": load_seconds, "peak_rss_bytes": memory.peak}


def metadata():
    import psutil
    git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout.strip()
    dirty = bool(subprocess.run(["git", "diff", "--name-only"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.strip())
    versions = {}
    for name in ("torch", "transformers", "faster-whisper", "jiwer", "sacrebleu", "psutil", "websockets"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return {"git_commit": git, "tracked_changes": dirty,
            "platform": platform.platform(), "cpu": platform.processor(),
            "physical_cores": psutil.cpu_count(logical=False),
            "logical_cores": psutil.cpu_count(logical=True),
            "system_ram_bytes": psutil.virtual_memory().total,
            "python": sys.version, "versions": versions,
            "created_utc": datetime.now(timezone.utc).isoformat()}


def fmt(value):
    return "n/a" if value is None else f"{value:.3f}"


def write_reports(output, results, meta):
    rows = [row for result in results for row in result["rows"]]
    with (output / "metrics.csv").open("x", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    lines = ["# Translation evaluation", "", f"Commit: `{meta['git_commit']}`",
             f"Tracked changes: {meta['tracked_changes']}", "",
             "| Profile | Clips | Mean WER | Mean CER | Mean chrF | Processing p50/p95 (s) | "
             "End-of-speech p95 (s) | Peak RAM (GiB) | Cost estimate ($) |",
             "|---|---:|---:|---:|---:|---|---:|---:|---:|"]
    for result in results:
        group = result["rows"]
        processing = [x for p in result["predictions"] for x in p["processing_latencies_s"]]
        end = [x for p in result["predictions"] for x in p["speech_end_latencies_s"]]
        lines.append(f"| {result['profile']} | {len(group)} | "
                     f"{np.mean([x['wer'] for x in group]):.3f} | "
                     f"{np.mean([x['cer'] for x in group]):.3f} | "
                     f"{np.mean([x['chrf'] for x in group]):.2f} | "
                     f"{fmt(percentile(processing, 50))} / {fmt(percentile(processing, 95))} | "
                     f"{fmt(percentile(end, 95))} | {result['peak_rss_bytes'] / 2**30:.2f} | "
                     f"{sum(float(x['estimated_cost_usd']) for x in group):.4f} |")
    for result in results:
        group = result["rows"]
        lines.extend(["", f"## {result['profile']}: bilingual metrics", ""])
        for label, numerator, denominator in (
            ("Language-tag accuracy", "tag_correct", "tag_count"),
            ("English-term recall", "english_terms_recalled", "english_terms_total"),
            ("Annotated transliteration rate", "transliterated_terms", "annotated_terms_total"),
            ("Unnecessary MT rate (Listen to English)", "unnecessary_mt_count", "english_utterances"),
        ):
            total = sum(x[denominator] or 0 for x in group)
            value = sum(x[numerator] or 0 for x in group) / total if total else None
            lines.append(f"- {label}: {fmt(value)} ({total} reference items)")
        lines.append(f"- Repetition loops: {sum(x['repetition_loops'] for x in group)}")
        lines.append(f"- Model load: {result['model_load_s']:.2f}s (excluded from segment latency)")
        lines.append(f"- Errors: {sum(x['error_count'] for x in group)}")
    lines.extend(["", "Metrics are clip means; raw counts and per-clip values are in metrics.csv.",
                  "Tag scores align reference utterances and output rows by order; missing/extra rows count as wrong.",
                  "Transliteration is measured only for explicitly annotated Arabic spellings; n/a is not zero.",
                  "Legacy segmentation has no speech-end timestamps, so its end-of-speech latency is n/a.",
                  "Faster-than-real-time replay measures compute and endpoint delay, not real-time queue contention.",
                  "No Saudi-meeting accuracy claim follows from a synthetic or MSA smoke clip.", ""])
    if any(result["profile"] in STREAMING_PROFILES for result in results):
        lines.extend(["Streaming costs retain the complete owner-approved session allocation, not an observed invoice.",
                      "Account ceilings must be independently verified; no advertised hourly price is a billing guarantee.",
                      "Soniox is clip-scored: per-utterance tags and timestamp latency are unavailable.",
                      "ElevenLabs EOF uses a post-EOF commit plus bounded quiet drain, not a server EndOfTranscript.",
                      "Missing latency is n/a and cannot establish the live-latency acceptance criterion.", ""])
    (output / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    (output / "run.json").write_text(json.dumps({"metadata": meta, "results": results},
                                               ensure_ascii=False, indent=2), encoding="utf-8")


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    inputs = result.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--input", type=Path, help="Folder containing WAVs and .ref.* sidecars")
    inputs.add_argument("--manifest", type=Path, help="Private sets.local.json with a clips list")
    result.add_argument("--profiles", default="baseline", help="Comma-separated: baseline,offline,free_cloud," + ",".join(STREAMING_PROFILES))
    result.add_argument("--source", default="ar")
    result.add_argument("--target", default="en")
    result.add_argument("--whisper-model", default="openai/whisper-small")
    result.add_argument("--legacy-fixed-window", action="store_true")
    result.add_argument("--allow-downloads", action="store_true",
                        help="Allow model downloads, never cloud audio/text uploads")
    result.add_argument("--allow-cloud", action="store_true",
                        help="Explicitly allow free_cloud to upload the evaluation clips/text to enabled, tested providers")
    result.add_argument("--allow-paid", action="store_true", help="Allow only streaming evaluations covered by --paid-policy")
    result.add_argument("--paid-policy", type=Path, help="Owner-approved allocation, verified session ceilings and credential fingerprints")
    result.add_argument("--paid-usage", type=Path, help="Persistent evaluation-only monthly ledger; defaults below --output")
    result.add_argument("--paid-run-usage", type=Path, help=argparse.SUPPRESS)
    result.add_argument("--stream-mt", choices=["offline", "free_cloud"], default="offline",
                        help="Desktop MT chain for Speechmatics/ElevenLabs; free_cloud uses saved enabled/Test checks")
    result.add_argument("--output", type=Path, default=ROOT / "tools/eval/results")
    result.add_argument("--bench", action="store_true", help="Benchmark local recognizers only")
    result.add_argument("--recognizers", default="cohere-fp32,cohere-bf16,cohere-int8,turbo-int8,base-lid")
    result.add_argument("--worker", choices=["eval", "bench"], help=argparse.SUPPRESS)
    result.add_argument("--result-file", type=Path, help=argparse.SUPPRESS)
    return result


def main(argv=None):
    # Windows redirected consoles can default to cp1252. The app prints source
    # text; an Arabic print failure must never be mistaken for an ASR failure.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    args = parser().parse_args(argv)
    paid_profiles = set(args.profiles.split(",")) & set(STREAMING_PROFILES)
    for profile in paid_profiles:
        PaidPolicy.read(args.paid_policy, profile, allow_cloud=args.allow_cloud, allow_paid=args.allow_paid)
    if paid_profiles and (args.source != "ar" or args.target not in {"ar", "en"} or args.bench):
        raise ValueError("Streaming evaluation is restricted to Arabic/English captions, not local recognizer benchmarks")
    if args.paid_usage is None:
        args.paid_usage = args.output / "paid-usage.json"
    if args.worker:
        if paid_profiles and args.paid_run_usage is None:
            raise ValueError("The parent runner must supply the shared paid run ledger")
        with nullcontext() if args.allow_downloads or (args.allow_cloud and args.profiles == "free_cloud") or paid_profiles else block_network():
            if args.worker == "bench":
                from tools.eval.bench import benchmark
                result = benchmark(args)
            else:
                result = evaluate_profile(find_clips(args.input, args.manifest), args.profiles, args)
        with args.result_file.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, ensure_ascii=False, indent=2)
        return
    # Every profile/model gets its own process, isolating offline flags, caches,
    # model load time and peak memory. Existing runs are never overwritten.
    if not args.bench:
        clips = find_clips(args.input, args.manifest)
        unsupported = set(args.profiles.split(",")) - {"baseline", "offline", "free_cloud", *STREAMING_PROFILES}
        if unsupported:
            raise ValueError(f"Profiles not yet implemented: {', '.join(sorted(unsupported))}")
        if "free_cloud" in args.profiles.split(",") and not args.allow_cloud:
            raise ValueError("free_cloud requires explicit --allow-cloud consent to upload evaluation audio/text")
        if paid_profiles:
            from tools.eval.streaming_runner import MAX_CLIP_SECONDS
            for clip in clips:
                samples, rate = read_audio(clip["path"])
                if len(samples) / rate > MAX_CLIP_SECONDS:
                    raise ValueError("Streaming evaluation clips must be at most 90 seconds")
    output = args.output / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    output.mkdir(parents=True, exist_ok=False)
    args.paid_run_usage = output / "paid-run-usage.json"
    meta = metadata()
    names = args.recognizers.split(",") if args.bench else args.profiles.split(",")
    results = []
    for index, name in enumerate(names):
        result_path = output / f"worker-{index}.json"
        cmd = [sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()), "--worker",
               "bench" if args.bench else "eval", "--result-file", str(result_path),
               "--source", args.source, "--target", args.target,
               "--whisper-model", args.whisper_model,
               "--recognizers" if args.bench else "--profiles", name]
        cmd += ["--manifest", str(args.manifest)] if args.manifest else ["--input", str(args.input)]
        if args.allow_downloads:
            cmd.append("--allow-downloads")
        if args.allow_cloud and name == "free_cloud":
            cmd.append("--allow-cloud")
        if name in STREAMING_PROFILES:
            cmd += ["--allow-cloud", "--allow-paid", "--paid-policy", str(args.paid_policy),
                    "--paid-usage", str(args.paid_usage.resolve()), "--paid-run-usage", str(args.paid_run_usage.resolve()),
                    "--stream-mt", args.stream_mt]
        if args.legacy_fixed_window:
            cmd.append("--legacy-fixed-window")
        subprocess.run(cmd, check=True, cwd=ROOT)
        results.append(json.loads(result_path.read_text(encoding="utf-8")))
    if args.bench:
        from tools.eval.bench import write_bench_report
        write_bench_report(output, results, meta)
    else:
        write_reports(output, results, meta)
    print(f"Reports: {output}")
    if not args.bench and any(row["error_count"] for result in results for row in result["rows"]):
        raise SystemExit("Pipeline errors occurred; this run cannot establish a quality baseline.")


if __name__ == "__main__":
    main()
