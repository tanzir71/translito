"""Opt-in Windows virtual-mic setup; kept out of Listen Mode."""
from ui_dispatch import post
from ui_scale import px, scaled_geometry
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from app_config import CONFIG_FILE, read_config, write_config
from engines import virtual_mic as cable


# Menu paths checked against the vendors' help pages on 2026-11-02.
GUIDES = {
    "Zoom": ("Profile picture → Settings → Audio.\nUnder Microphone, choose CABLE Output (VB-Audio Virtual Cable).\nKeep Speaker set to your headphones.",
        "https://support.zoom.com/hc/en/article?id=zm_kb&sysparm_article=KB0060836"),
    "Microsoft Teams": ("Settings and more (…) → Settings → Devices.\nUnder Audio settings → Microphone, choose CABLE Output (VB-Audio Virtual Cable).\nKeep Speaker set to your headphones.",
        "https://support.microsoft.com/en-us/teams/notifications-settings/manage-your-device-settings-in-microsoft-teams"),
    "Slack": ("Profile picture → Preferences → Audio & video.\nUnder Microphone, choose CABLE Output (VB-Audio Virtual Cable).\nKeep Speaker set to your headphones.",
        "https://slack.com/help/articles/1500002037922-Adjust-your-huddles-preferences"),
    "Google Meet": ("Open your meeting preview, then More options → Settings → Audio.\nChoose CABLE Output (VB-Audio Virtual Cable) as Microphone.\nKeep Speaker set to your headphones.",
        "https://support.google.com/meet/answer/10409699?hl=en-EN"),
    "Discord": ("User Settings (gear) → Voice & Video.\nChoose CABLE Output (VB-Audio Virtual Cable) as Input Device.\nKeep Output Device set to your headphones.",
        "https://support.discord.com/hc/en-us/articles/33030151293079-Discord-Voice-Video-Streaming-Guide"),
    "Other": ("Open your meeting app's Audio settings.\nChoose CABLE Output (VB-Audio Virtual Cable) as its microphone.\nChoose headphones as its speaker; keep your real microphone selected in Translito.", None),
}


class VirtualMicSetup:
    def __init__(self, host, colors):
        self.host, self.colors = host, colors
        self.tested_name = ""
        self.failed = False
        self.restart_needed = False
        self.force_visible = False
        self.poll_stop = threading.Event()
        config = read_config(CONFIG_FILE)
        self.meeting_app = config.get("VIRTUAL_MIC", "meeting_app", fallback="Zoom")
        self.confirmed_app = config.get("VIRTUAL_MIC", "confirmed_app", fallback="")
        if self.meeting_app not in GUIDES:
            self.meeting_app = "Other"
        self.frame = tk.Frame(host.root, bg=colors["surface"], padx=px(12), pady=px(12),
                              highlightbackground=colors["border"], highlightthickness=px(1))
        self.heading = tk.Label(self.frame, text="Speak Mode setup", bg=colors["surface"], fg=colors["text"],
                                anchor="w", font=("Segoe UI Semibold", 10))
        self.heading.pack(fill="x", pady=px((0, 6)))
        self.steps = tk.StringVar()
        self.steps_label = tk.Label(self.frame, textvariable=self.steps, bg=colors["surface"], fg=colors["secondary"],
                 anchor="w", justify="left", font=("Segoe UI", 8))
        self.steps_label.pack(fill="x")
        self.label = tk.Label(self.frame, text="", bg=colors["surface"], fg=colors["secondary"],
                              anchor="w", justify="left", wraplength=px(700), font=("Segoe UI", 9))
        self.label.pack(fill="x", pady=px((6, 10)))
        actions = self.actions = tk.Frame(self.frame, bg=colors["surface"])
        actions.pack(fill="x")
        self.install_button = ttk.Button(actions, text="Install virtual mic", style="Mac.TButton", command=self.consent)
        self.install_button.pack(side="left", padx=px((0, 6)))
        self.test_button = ttk.Button(actions, text="Test virtual mic", style="Mac.TButton", command=self.test)
        self.test_button.pack(side="left", padx=px((0, 6)))
        self.guide_button = ttk.Button(actions, text="Pick meeting mic…", style="Mac.TButton", command=self.guide)
        self.guide_button.pack(side="left", padx=px((0, 6)))
        self.sound_button = ttk.Button(actions, text="Sound settings", style="Mac.TButton", command=self.sound_settings)
        self.sound_button.pack(side="left")
        self.restart_button = ttk.Button(actions, text="Restart Windows…", style="Mac.TButton", command=self.restart)

    def update(self):
        output = self.host.selected_output_choice()
        installed = cable.cable_output(self.host.output_choices) is not None
        selected = bool(output and "cable input" in output.name.lower())
        passed = selected and self.tested_name == output.name and not self.failed
        confirmed = self.confirmed_app == self.meeting_app
        background = self.colors["yellow_bg"] if self.failed else self.colors["surface"]
        for widget in (self.frame, self.heading, self.steps_label, self.label, self.actions):
            widget.configure(bg=background)
        self.heading.configure(text="Check your virtual microphone" if self.failed else "Speak Mode setup")
        mark = lambda value: "✓" if value else "○"
        self.steps.set(f"{mark(installed)} 1. Install virtual mic     {mark(passed)} 2. Test     {mark(confirmed)} 3. Pick it in your meeting app")
        if self.restart_needed and not installed:
            text = "Restart Windows to finish installing the virtual mic. Save your work before restarting."
        elif not installed:
            text = "Add a virtual microphone to send your translated voice into calls. VB-CABLE by VB-Audio is included with Translito and only needs to be installed once."
        elif not selected:
            text = "Select CABLE Input under Speak to, then test. Your meeting app uses CABLE Output as its microphone."
        elif self.failed:
            text = "The virtual-mic test failed. Check CABLE Input / Output mute and levels in Windows Sound settings, then test again."
        elif not passed:
            text = "Your virtual microphone is ready. Choose CABLE Output as the microphone in your meeting app. Translito checks the route when you press Start."
        else:
            text = "Virtual microphone passed. Finish step 3 in your meeting app, then confirm it below."
        self.label.configure(text=text)
        idle = self.host.transcriber is None and not self.host.model_setup_busy
        self.install_button.configure(state="normal" if idle and not installed else "disabled")
        if installed:
            self.install_button.pack_forget()
        else:
            self.install_button.pack(side="left", before=self.test_button, padx=px((0, 6)))
        self.test_button.configure(state="normal" if idle and selected else "disabled")
        self.guide_button.configure(state="normal" if idle else "disabled")
        if self.restart_needed and not installed:
            self.restart_button.pack(side="right")
        else:
            self.restart_button.pack_forget()
        self.restart_button.configure(state="normal" if idle else "disabled")
        if self.host.mode_var.get() == "speak" and (self.force_visible or not installed or not selected or self.failed):
            self.frame.grid(row=3, column=0, sticky="ew")
        else:
            self.frame.grid_remove()

    def _dispatch(self, callback):
        if self.host.is_quitting:
            return
        try:
            post(self.host, callback)
        except (RuntimeError, tk.TclError):
            pass

    def _place(self, window):
        from gui import center_window
        center_window(window, self.host.root)

    def _work(self, work, finished, status):
        host = self.host
        if host.transcriber is not None or host.model_setup_busy:
            host.show_hint("Stop the session before changing virtual-mic setup.")
            return
        if host.preview_mode:
            host.show_hint("Preview only: no driver, sound, or Windows settings were changed.")
            return
        host.model_setup_busy = True
        host.lock_controls(True)
        host.update_action_button(loading=True)
        host.set_status(status)
        self.update()
        def run():
            try:
                result, error = work(), None
            except Exception as exc:
                result, error = None, exc
            def done():
                host.model_setup_busy = False
                host.lock_controls(False)
                host.update_action_button()
                host.set_status("Ready")
                if error is not None:
                    host.show_error(str(error) if isinstance(error, cable.VirtualMicError) else "Virtual-mic setup could not finish. Try again or open Sound settings.")
                else:
                    finished(result)
                self.update()
            self._dispatch(done)
        threading.Thread(target=run, daemon=True, name="Translito virtual mic setup").start()

    def consent(self):
        if self.host.preview_mode:
            self.host.show_hint("Preview only: no driver installer was started.")
            return
        if self.host.transcriber is not None or self.host.model_setup_busy:
            return
        window = tk.Toplevel(self.host.root)
        from windows_icons import apply_window_icon
        window.after_idle(lambda: apply_window_icon(window))
        window.title("Install VB-CABLE by VB-Audio")
        window.configure(bg=self.colors["bg"])
        window.transient(self.host.root)
        window.grab_set()
        tk.Label(window, text="What does this install?", bg=self.colors["bg"], fg=self.colors["text"],
                 font=("Segoe UI Semibold", 12)).pack(anchor="w", padx=px(20), pady=px((18, 8)))
        tk.Label(window, text="VB-CABLE adds a virtual playback / microphone pair to Windows. Translito sends translated speech to CABLE Input; your meeting app records CABLE Output.\n\nVB-CABLE is donationware by VB-Audio. You can review its terms and donate below. Organizations that cannot expose donation/payment to their users need the appropriate VB-Audio license.\n\nOnly the driver installer requests administrator access. Expect Windows permission and driver-publisher prompts. A restart may be needed. Translito will not restart Windows automatically.",
                 bg=self.colors["bg"], fg=self.colors["secondary"], wraplength=px(490), justify="left").pack(padx=px(20))
        links = tk.Frame(window, bg=self.colors["bg"])
        links.pack(fill="x", padx=px(20), pady=px(12))
        for title, url in [("What is VB-CABLE?", cable.PACKAGE["product"]), ("Terms / Donate to VB-Audio", cable.PACKAGE["donate"])]:
            ttk.Button(links, text=title, command=lambda url=url: webbrowser.open(url), style="Mac.TButton").pack(side="left", padx=px((0, 8)))
        actions = tk.Frame(window, bg=self.colors["bg"])
        actions.pack(fill="x", padx=px(20), pady=px((0, 18)))
        ttk.Button(actions, text="Cancel", command=window.destroy, style="Mac.TButton").pack(side="right")
        def install():
            window.destroy()
            self.poll_stop.clear()
            def work():
                cable.install_virtual_mic(consent=True)
                return cable.wait_for_cable(stop_event=self.poll_stop)
            def done(output):
                self.restart_needed = output is None
                self.host.refresh_devices()
                if output is not None:
                    self.host.select_combo_by_name(self.host.speak_output_combo, self.host.output_choices, output.name)
                    self.host.persist_settings()
                    self.host.show_hint("Virtual microphone found and selected. Run Test virtual mic next.")
            self._work(work, done, "Waiting for virtual microphone")
        ttk.Button(actions, text="Install optional driver", command=install, style="Primary.TButton").pack(side="right", padx=px(8))
        self._place(window)

    def test_result(self, output, result):
        self.failed = not result.passed
        self.tested_name = output.name if output and result.passed else ""
        self.update()

    def test(self):
        output = self.host.selected_output_choice()
        def done(result):
            self.test_result(output, result)
            self.host.show_hint(result.message)
        self._work(lambda: cable.self_test(output), done, "Testing virtual microphone")

    def guide(self):
        window = tk.Toplevel(self.host.root)
        from windows_icons import apply_window_icon
        window.after_idle(lambda: apply_window_icon(window))
        window.title("Choose your meeting microphone")
        window.configure(bg=self.colors["bg"])
        window.transient(self.host.root)
        variable = tk.StringVar(value=self.meeting_app)
        combo = ttk.Combobox(window, textvariable=variable, values=list(GUIDES), state="readonly", style="Dark.TCombobox")
        combo.pack(fill="x", padx=px(18), pady=px(16))
        label = tk.Label(window, bg=self.colors["bg"], fg=self.colors["text"], justify="left", wraplength=px(480))
        label.pack(fill="x", padx=px(18))
        def selected(_event=None):
            label.configure(text=GUIDES[variable.get()][0])
        combo.bind("<<ComboboxSelected>>", selected)
        selected()
        def help_page():
            url = GUIDES[variable.get()][1]
            if url:
                webbrowser.open(url)
        ttk.Button(window, text="Official app instructions", command=help_page, style="Mac.TButton").pack(anchor="w", padx=px(18), pady=px(10))
        def confirm():
            self.meeting_app = self.confirmed_app = variable.get()
            if not self.host.preview_mode:
                config = read_config(CONFIG_FILE)
                if "VIRTUAL_MIC" not in config:
                    config["VIRTUAL_MIC"] = {}
                config["VIRTUAL_MIC"]["meeting_app"] = self.meeting_app
                config["VIRTUAL_MIC"]["confirmed_app"] = self.confirmed_app
                write_config(config, CONFIG_FILE)
            self.force_visible = False
            window.destroy()
            self.update()
        ttk.Button(window, text="I've selected CABLE Output in my meeting app", command=confirm, style="Primary.TButton").pack(padx=px(18), pady=px((0, 16)))
        self._place(window)

    def sound_settings(self):
        if self.host.preview_mode:
            self.host.show_hint("Preview only: Windows settings were not opened.")
        else:
            os.startfile("ms-settings:sound")

    def restart(self):
        if self.host.preview_mode or self.host.transcriber is not None or self.host.model_setup_busy:
            return
        if messagebox.askyesno("Restart Windows", "Save your work first. Restart Windows now to finish the virtual-mic installation?", parent=self.host.root, default="no"):
            cable.restart_windows(consent=True)
