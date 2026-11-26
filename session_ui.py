"""One desktop readiness controller; downloads never own session state."""
from dataclasses import replace
import os
import threading

from engines.engine_status import EngineStatus
from engines.session_state import ReadinessState, normalized_settings, readiness, resolve_plan
from engines.settings import load_engine_settings, credential_signature


class SessionController:
    def __init__(self, app):
        self.app, self.plan, self.state = app, None, ReadinessState("preparing", "Preparing setup")
        self.generation, self.pending, self.active_owner = 0, None, None
        self.active_plan, self.actual_engines, self.failure = None, {}, ""
        self.active_token = None
        self._refreshing, self._signature = False, None
        self.credentials, self.checking, self.checked_signature = {}, False, None
        self.timer = app.root.after(100, self.tick)

    def settings(self):
        settings = normalized_settings(load_engine_settings(self.app.preferences.path))
        if self.app.preview_mode:
            settings = normalized_settings(replace(settings, engine_choice=self.app.engine_choice_var.get()))
        return settings

    def context(self):
        app = self.app
        mode = app.mode_var.get()
        conversation = app.current_conversation()
        if conversation.one_way:
            names = (app.speak_source_var, app.speak_target_var) if mode == "speak" else (app.listen_source_var, app.listen_target_var)
            pair = tuple(app.language_entry_by_name(var.get())[2] for var in names)
        else:
            target = conversation.my_language if mode == "listen" else conversation.audience_language
            pair = (conversation.other_language if target == "en" else "en", target)
        return mode, pair, conversation

    def _check_key(self, settings, pair):
        selected = {name: pref for name, pref in settings.providers.items() if pref.enabled and pref.tested_signature}
        identity = tuple((name, pref.tested_signature) for name, pref in selected.items())
        if settings.engine_choice == "local" or self.checked_signature == identity or self.checking:
            return
        self.checking = True
        def work():
            results = {}
            try:
                from engines.secrets import CredentialStore
                store = getattr(self.app, "credential_store", None) or CredentialStore()
                for name, pref in selected.items():
                    key = store.get(name)
                    results[name] = bool(key and credential_signature(name, key, pref) == pref.tested_signature)
            except Exception:
                results = {name: False for name in selected}
            def done():
                self.credentials, self.checked_signature, self.checking = results, identity, False
                self.refresh()
            if not self.app.is_quitting:
                self.app.post_ui(done)
        threading.Thread(target=work, daemon=True, name="Check saved provider").start()

    def reset_connection(self):
        self.credentials.clear()
        self.checked_signature, self.failure = None, ""
        self.refresh()

    def refresh(self):
        app = self.app
        if self._refreshing or app.is_quitting:
            return self.status()
        self._refreshing = True
        try:
            settings = self.settings()
            mode, pair, _ = self.context()
            identity = (mode, pair, repr(settings), app.whisper_var.get(), app.listen_device_var.get(),
                        app.speak_mic_var.get(), app.speak_output_var.get(), app.offline_only_var.get())
            if self._signature is not None and identity != self._signature:
                self.generation += 1
                if app.transcriber is None and app.model_setup_busy and self.pending is not None:
                    self.pending = None
                    app.model_setup_busy = False
                    app.lock_controls(False)
                    app.finish_model_progress()
                if app.transcriber is None and not app.model_setup_busy:
                    self.pending = None
                    if getattr(app, "_waiting_meeting_app", False):
                        from meeting_app import cancel_wait
                        cancel_wait(app)
            self._signature = identity
            if not app.preview_mode and not app.offline_only_var.get():
                self._check_key(settings, pair)
            from engines.usage import UsageLedger
            usage = None if app.preview_mode else UsageLedger().snapshot()
            self.plan = resolve_plan(settings, pair, mode=mode, preferred_whisper=app.whisper_var.get(),
                block_all=app.offline_only_var.get(), usage=usage, credentials=self.credentials,
                failure=self.failure if app.transcriber is None else "")
            manager = app.download_manager
            auto = (not app.preview_mode and app.preferences.get("MODELS", "auto_prepare_basic", True)
                    and os.environ.get("TRANSLITO_AUTO_SETUP_DISABLED") != "1")
            if not app.preview_mode:
                try:
                    manager.reconcile_setup(self.plan.required_resources, self.plan.backup_resources,
                        context=f"{mode.title()} · {pair[0]} → {pair[1]}", enabled=auto)
                except (OSError, ValueError) as error:
                    if self.plan.required_resources:
                        self.state = ReadinessState("setup_required", str(error), "models")
                        self.render()
                        return self.status()
            self.state = readiness(self.plan, jobs=manager.jobs, blocked=app.offline_only_var.get())
            if self.checking and not self.plan.blockers:
                self.state = ReadinessState("preparing", "Checking saved connection", "engine")
            issue = self.audio_issue()
            if issue and not self.plan.blockers:
                self.state = issue
            if getattr(app, "_stopping", False):
                self.state = ReadinessState("stopping", "Stopping session")
            elif app.transcriber is not None:
                self.state = ReadinessState("recovering" if self.failure else "running", self.failure or "Listening")
            elif app.model_setup_busy:
                self.state = ReadinessState("starting", "Starting session")
            elif getattr(app, "_waiting_meeting_app", False):
                self.state = ReadinessState("waiting", "Waiting for meeting audio")
            self.render()
            return self.status()
        except (ValueError, KeyError) as error:
            self.state = ReadinessState("setup_required", str(error), "languages")
            self.render()
            return self.status()
        finally:
            self._refreshing = False

    def audio_issue(self):
        app = self.app
        if app.preview_mode or self.plan is None:
            return None
        if self.plan.mode == "speak":
            desired = app.preferences.get("SPEAK", "speak_mic_name", "")
            if desired and not any(c.name == desired for c in app.speak_mic_choices):
                return ReadinessState("setup_required", "Your saved microphone is disconnected.", "audio")
            if app.selected_speak_mic_choice() is None:
                return ReadinessState("setup_required", "Choose a microphone for Speak mode.", "audio")
            output = app.selected_output_choice()
            if output is None or "cable input" not in output.name.casefold():
                return ReadinessState("setup_required", "Finish virtual microphone setup.", "virtual_mic")
            if app.voice_hint_var.get():
                return ReadinessState("setup_required", app.voice_hint_var.get(), "voice")
        elif app.listen_source_type_var.get() == "Device":
            desired = app.preferences.get("CAPTURE", "device_name", "") or app.preferences.get("DEVICE", "name", "")
            if desired and not any(c.name == desired for c in app.listen_choices):
                return ReadinessState("setup_required", "Your saved audio device is disconnected.", "audio")
            if app.selected_listen_choice() is None:
                return ReadinessState("setup_required", "Choose an audio source.", "audio")
        elif app.selected_listen_choice() is None and not (app.default_app_var.get() or app.preferences.get("CAPTURE", "app_executable", "")):
            return ReadinessState("setup_required", "Choose a meeting app or an audio device.", "audio")
        return None

    def status(self):
        plan = self.active_plan if self.app.transcriber is not None and self.active_plan else self.plan
        if plan is None:
            return EngineStatus("Setup", self.state.message)
        engine = plan.engine
        if self.actual_engines:
            from engines.cloud_connect import TITLES
            stages = [TITLES.get(self.actual_engines.get(k), self.actual_engines.get(k, "")) for k in ("asr", "mt")]
            if all(stages):
                engine = stages[0] if stages[0] == stages[1] else " / ".join(stages)
        reason = self.failure or plan.cloud_reason
        reason = {"Set a monthly budget to use cloud.": "needs a monthly budget",
                  "The monthly cloud budget is used up.": "budget used up"}.get(reason, reason)
        return EngineStatus(engine, reason)

    def render_action(self, running=False, loading=False):
        app = self.app
        button = app.speak_action_button if app.mode_var.get() == "speak" else app.listen_action_button
        other = app.listen_action_button if button is app.speak_action_button else app.speak_action_button
        busy = app.transcriber is not None or app.model_setup_busy or getattr(app, "_waiting_meeting_app", False)
        other.configure(state="disabled" if busy else "normal")
        if self.state.phase == "stopping":
            button.configure(text="Stopping…", style="Mac.TButton", state="disabled")
        elif busy:
            button.configure(text="Stop", style="Stop.TButton", state="normal")
        elif self.state.can_start:
            button.configure(text="Start", style="Primary.TButton", state="normal")
        else:
            labels = {"connect": "Connect", "budget": "Budget", "resume": "Resume", "languages": "Languages",
                      "audio": "Audio", "virtual_mic": "Set up", "voice": "Voice", "privacy": "Privacy", "engine": "Engine"}
            button.configure(text="Preparing…" if self.state.phase == "preparing" else labels.get(self.state.action, "Setup"),
                style="Mac.TButton", state="disabled" if self.state.phase == "preparing" else "normal")

    def render(self):
        app = self.app
        status = self.status()
        app.engine_var.set(status.text)
        from gui import COLORS
        app.engine_label.configure(fg=COLORS["orange" if self.failure else "secondary"], cursor="hand2")
        app.engine_label.bind("<Button-1>", lambda event: self.open_action("engine"))
        self.render_action()
        app.empty_help_label.configure(text=self.state.message if not self.state.can_start else
            f"Using {status.engine}. Choose your audio source and press Start.")
        remote = self.plan and (self.plan.asr != "local" or self.plan.mt != "local")
        app.empty_measurements_var.set("Speech or text goes only to your connected engines. Local backup prepares in the background."
            if remote else "Your cloud preference is saved. This session uses this PC."
            if self.plan and self.plan.preferred_engine == "cloud" else "Audio and text stay on this PC with a local engine.")
        if self.active_plan and self.plan and self.active_plan.pair != self.plan.pair:
            app.empty_measurements_var.set("Language changes apply to the next session. Preparing the new pair in the background.")
        actions = getattr(app, "empty_actions", None)
        if actions is not None:
            offer = (not app.preferences.get("UI", "setup_offer_seen", True)
                     and self.plan and self.plan.preferred_engine == "local")
            # A hidden second action must not leave an equal-width empty column.
            actions.columnconfigure(0, weight=1, uniform="empty-state-actions" if offer else "")
            actions.columnconfigure(1, weight=1 if offer else 0, uniform="empty-state-actions" if offer else "")
            app.empty_setup_button.grid_configure(padx=__import__("ui_scale").px((0, 4) if offer else 0))
            if offer:
                actions.pack(pady=__import__("ui_scale").px((12, 0)))
                app.empty_setup_button.configure(text="Set up cloud", command=app.open_cloud_setup)
                app.empty_local_button.grid()
            elif self.state.phase == "setup_required":
                actions.pack(pady=__import__("ui_scale").px((12, 0)))
                app.empty_setup_button.configure(text={"connect": "Connect cloud", "budget": "Set budget", "resume": "Resume setup"}.get(self.state.action, "Open setup"),
                                                 command=lambda: self.open_action(self.state.action))
                app.empty_local_button.grid_remove()
            else:
                actions.pack_forget()

    def open_action(self, action):
        app = self.app
        if action == "virtual_mic":
            app.show_virtual_mic_setup()
            return
        if action == "resume":
            from engines.downloads import job_for_repo
            for spec in self.plan.required_resources:
                job = job_for_repo(app.download_manager.jobs, spec.repo)
                if job:
                    app.download_manager.resume(job)
                else:
                    app.download_manager.enqueue_model(spec)
            self.refresh()
            return
        app.open_settings()
        page = {"models": "Models", "privacy": "General", "languages": "Languages", "audio": "Audio", "voice": "Audio"}.get(action, "Engine")
        app.settings_shell.show(page)

    def before_start(self, *, interactive=True):
        if not self.app.preferences.commit_pending():
            self.app.show_hint("Correct the highlighted settings before starting.")
            return False
        self.refresh()
        state = readiness(self.plan, jobs=self.app.download_manager.jobs, blocked=self.app.offline_only_var.get()) if getattr(self.app, "_waiting_meeting_app", False) else self.state
        if not state.can_start:
            if interactive and self.state.phase == "setup_required":
                self.open_action(self.state.action)
            return False
        return True

    def begin(self, owner="manual"):
        token = (self.generation, owner)
        self.pending = token
        return token

    def accepts(self, token):
        return self.pending == token and token[0] == self.generation and not self.app.is_quitting

    def allows_event(self, token):
        return self.accepts(token) or self.active_token == token

    def started(self, token, plan=None):
        self.active_token = token
        self.active_owner, self.active_plan, self.pending = token[1], plan or self.plan, None
        self.actual_engines, self.failure = {}, ""
        self.app.preferences.set("UI", "setup_offer_seen", True)

    def cancel(self):
        self.generation += 1
        self.pending = None

    def tick(self):
        if self.app.is_quitting:
            return
        self.refresh()
        self.timer = self.app.root.after(1000, self.tick)

    def close(self):
        self.cancel()
        self.active_token = None
        if self.timer:
            try:
                self.app.root.after_cancel(self.timer)
            except Exception:
                pass
