"""The 800px comparison dialog. Running a check is always an explicit action."""
from ui_scale import px, scaled_geometry
from decimal import Decimal
import threading
import tkinter as tk
from tkinter import filedialog, ttk

from engines.checks import CheckRunner, CheckStore, SampleCatalog, local_engine, cloud_engine
from engines.registry import provider_factories, build_session_routers
from engines.settings import load_engine_settings
from engine_ui import heading, pair, refresh_measurements
from quality_settings import _window


def open_check(app, colors, center, *, first_run=False):
    window = _window(app, "Speed and accuracy check", colors, center, 800, 546)
    body = tk.Frame(window, bg=colors["bg"], padx=px(24), pady=px(22))
    body.pack(fill="both", expand=True)
    heading(body, "Speed and accuracy check", "The same public clips run through every engine. Accuracy stays blank for recordings without references.", colors)
    source, target = pair(app)
    samples, results = [], []
    status = tk.StringVar(value="Load the public sample or choose a recording. No microphone is opened.")
    top = tk.Frame(body, bg=colors["bg"])
    top.pack(fill="x", pady=px(8))
    columns = ("Engine", "Delay p50 / p95", "Words right", "Terms kept", "Cost / speech h")
    tree = ttk.Treeview(body, columns=columns, show="headings", height=px(8, chars=True))
    for column in columns:
        tree.heading(column, text=column)
        tree.column(column, width=px(140 if column == "Engine" else 125), stretch=True)
    tree.pack(fill="both", expand=True, pady=px(12))
    from ui_theme import apply_theme
    apply_theme(window, app.style, colors)
    tk.Label(body, textvariable=status, bg=colors["bg"], fg=colors["secondary"], wraplength=px(740), justify="left", anchor="w").pack(fill="x", pady=px(8))
    settings = load_engine_settings(app.preferences.path)
    connected = [f for f in provider_factories() if f.kind == "live" and settings.provider(f.name).enabled and settings.provider(f.name).tested_signature and not f.unavailable_reason(source, target)]
    for name in ["On this PC", *[f.title for f in provider_factories() if f.kind == "live"]]:
        tree.insert("", "end", values=(name, "not measured", "not measured", "not measured", "estimate / account limits"))
    def estimate_text():
        hours = Decimal(str(sum(s.seconds for s in samples))) / 3600
        estimate = sum((f.rate.per_audio_hour * hours for f in connected if f.rate), Decimal(0))
        status.set(f"{len(samples)} clips · {sum(s.seconds for s in samples):.1f} s. Base audio list estimate ${estimate:.4f}; text tokens and conservative reservations are additional. Monthly and provider caps apply.")
    def background(work, finish, *, owns_setup=False):
        def run():
            try:
                value, error = work(), None
            except Exception:
                value, error = None, "Check unavailable. Verify the cached models, connected providers, sample and budget."
            def complete():
                if owns_setup:
                    app.model_setup_busy = False
                if window.winfo_exists():
                    finish(value, error)
            app.root.after(0, complete)
        threading.Thread(target=run, daemon=True).start()
    def loaded(value, error):
        load_button.configure(state="normal")
        if error:
            status.set(error)
            return
        samples[:] = value
        estimate_text()
        run_button.configure(state="normal")
    def load():
        if app.preview_mode:
            status.set("Preview: no sample downloads, model loads or cloud requests.")
            return
        load_button.configure(state="disabled")
        variety, full = app.variety_var.get(), full_sample.get()
        background(lambda: SampleCatalog().public(source, target, variety=variety, full=full), loaded)
    def own():
        path = filedialog.askopenfilename(parent=window, filetypes=[("Audio recording", "*.wav *.flac *.mp3")])
        if path:
            background(lambda: [SampleCatalog.recording(path, source, target, variety=app.variety_var.get())], loaded)
    load_button = ttk.Button(top, text="Load public sample", style="Mac.TButton", command=load)
    load_button.pack(side="left")
    ttk.Button(top, text="Use my recording", style="Mac.TButton", command=own).pack(side="left", padx=px(8))
    full_sample = tk.BooleanVar(window, value=False)
    if source == "ar" and target == "en":
        tk.Checkbutton(top, text="Full set (300)", variable=full_sample,
            **{**app._checkbutton_options(), "bg": colors["bg"]}).pack(side="right")
    def run():
        if app.preview_mode or not samples or app.transcriber is not None:
            return
        run_button.configure(state="disabled")
        app.model_setup_busy = True
        def work():
            defaults = settings.resolve(source,target)
            model = defaults["default_asr_model"] if defaults["default_asr_provider"] == "local" else ""
            engines = [local_engine(source, target, model or app.whisper_var.get())]
            if connected and settings.profile != "offline":
                from engines.secrets import CredentialStore
                from engines.mt_quality import LocalQualityTranslator
                from engines.usage import UsageLedger
                from engines.lid import PairLanguageDetector
                from faster_whisper import WhisperModel
                from model_loading import _local_fast_whisper_model
                from types import SimpleNamespace
                cached = _local_fast_whisper_model("base")
                if cached is None:
                    raise ValueError("Cache the local language detector before using paid speech checks")
                lid = PairLanguageDetector(WhisperModel(cached, device="cpu", compute_type="int8", local_files_only=True), other=next(code for code in (source, target) if code != "en"))
                credentials, ledger = CredentialStore(), UsageLedger()
                _, translator = build_session_routers(SimpleNamespace(name="unused", requires_network=False),
                    LocalQualityTranslator(offline_only=True), settings, credentials=credentials, ledger=ledger, pair=(source,target))
                engines += [cloud_engine(f, settings, credentials=credentials, ledger=ledger, translator=translator, lid=lid) for f in connected]
            scored = []
            for engine in engines:
                try:
                    scored.extend(CheckRunner().run(samples, [engine]))
                except Exception:
                    continue
            if not scored:
                raise ValueError("No engine completed the check")
            CheckStore(app.preferences.path.parent / "checks.json").save(source, target, scored)
            return scored
        def finished(value, error):
            app.model_setup_busy = False
            run_button.configure(state="normal")
            if error:
                status.set(error)
                return
            results[:] = value
            refresh_measurements(app)
            tree.delete(*tree.get_children())
            def number(value, suffix=""):
                return "not measured" if value is None else f"{value:.1f}{suffix}"
            for row in results:
                tree.insert("", "end", values=(row["engine"], number(row["delay_p50_s"]," s")+" / "+number(row["delay_p95_s"]," s"),
                    number(row["words_right"],"%"), number(row["english_term_recall"]*100 if row["english_term_recall"] is not None else None,"%"), "$"+row["cost_per_speech_hour"]))
            recommendation = CheckRunner.recommend(results)
            status.set("Recommended: " + recommendation if recommendation else "No engine meets all recommendation criteria. Choose an engine in Settings.")
        background(work, finished, owns_setup=True)
    def transcripts():
        if not results:
            return
        detail = _window(app, "Check transcripts", colors, center, 760, 500)
        text = tk.Text(detail, wrap="word", bg=colors["field"], fg=colors["text"], padx=px(18), pady=px(18))
        text.pack(fill="both", expand=True)
        for result in results:
            text.insert("end", result["engine"] + "\n\n")
            for index, output in enumerate(result["outputs"], 1):
                text.insert("end", f"{index}. {output['source']}\n→ {output['target']}\n\n")
        text.configure(state="disabled")
    bottom = tk.Frame(body, bg=colors["bg"])
    bottom.pack(fill="x")
    ttk.Button(bottom, text="View transcripts", command=transcripts, style="Mac.TButton").pack(side="left", padx=px(8))
    run_button = ttk.Button(bottom, text="Run check", command=run, style="Primary.TButton", state="disabled")
    run_button.pack(side="right")
    window.results = results
    return window
