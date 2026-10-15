# """Tkinter dashboard for webcam/video detection and email alerts."""

import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
from PIL import Image, ImageTk

from config import Config
from detection import ObjectDetector
from email_alert import AlertSystem
from logger import logger


class AppGUI:
    BG = "#24384a"
    PANEL = "#2d4357"
    GREEN = "#22a879"
    RED = "#e74c3c"
    BLUE = "#2798d0"
    PURPLE = "#9658b8"
    TEAL = "#169f8a"

    def __init__(self, root):
        self.root = root
        self.root.title(Config.APP_NAME)
        self.root.geometry("1180x760")
        self.root.minsize(900, 620)
        self.root.configure(bg=self.BG)

        self.detector = ObjectDetector()
        self.alert_system = AlertSystem(cooldown=10)
        self.confidence_threshold = 0.70
        self.cooldown_seconds = 10
        self.receiver_email_value = Config.EMAIL_RECEIVER
        self.source_kind = None
        self.video_path = None
        self.frame_count = 0
        self.is_running = False
        self.pending_start = False
        self.closing = False
        self.email_warning_logged = False
        self.stop_event = None
        self.worker_thread = None
        self.messages = queue.Queue(maxsize=2)
        self._photo = None
        self._poll_id = None
        self._close_started_at = None

        self.confidence = tk.DoubleVar(value=self.confidence_threshold)
        self.cooldown = tk.IntVar(value=self.cooldown_seconds)
        self.receiver_email = tk.StringVar(value=self.receiver_email_value)
        self.status = tk.StringVar(value="Ready" if self.detector.is_ready else "Model unavailable")
        self.activity = tk.StringVar(value="STANDBY")
        self.frames = tk.StringVar(value="Frames: 0")
        self.detection_summary = tk.StringVar(value="No detections yet")

        self._style()
        self.setup_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.log("Surveillance Detection System ready.")
        if self.detector.is_ready:
            self.log(f"Model loaded. Classes: {', '.join(self.detector.class_names) or 'none reported'}")
        else:
            self.log(self.detector.load_error or "YOLO model is not ready.")
        self._poll_id = self.root.after(30, self._poll_worker_messages)

    def _style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=self.BG)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("TLabel", background=self.BG, foreground="#edf3f7", font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background=self.PANEL, foreground="#edf3f7", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=self.BG, foreground="#edf3f7", font=("Segoe UI", 19, "bold"))
        style.configure("Section.TLabel", background=self.PANEL, foreground="#edf3f7", font=("Segoe UI", 11, "bold"))
        style.configure("TButton", font=("Segoe UI", 9, "bold"), padding=7)
        style.configure("TEntry", fieldbackground="#f3f6f8", foreground="#172735")
        style.configure("TSpinbox", fieldbackground="#f3f6f8", foreground="#172735")
        style.configure("Horizontal.TScale", background=self.PANEL, troughcolor="#d6dde2")

    def setup_ui(self):
        header = ttk.Frame(self.root)
        header.pack(fill=tk.X, padx=14, pady=(12, 8))
        ttk.Label(header, text="🔒  AI-Based Surveillance Detection System", style="Title.TLabel").pack()

        top = ttk.Frame(self.root, style="Panel.TFrame", padding=12)
        top.pack(fill=tk.X, padx=12, pady=(0, 10))
        buttons = ttk.Frame(top, style="Panel.TFrame")
        buttons.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 18))
        self._button(buttons, "▶ Start Detection", self.start_detection, self.GREEN).grid(row=0, column=0, padx=(0, 6), pady=5)
        self._button(buttons, "■ Stop Detection", self.stop_detection, self.RED).grid(row=0, column=1, padx=6, pady=5)
        self._button(buttons, "▣ Load Video", self.load_video, self.BLUE).grid(row=0, column=2, padx=6, pady=5)
        self._button(buttons, "▣ Use Camera", self.use_camera, self.PURPLE).grid(row=0, column=3, padx=6, pady=5)

        status_area = ttk.Frame(top, style="Panel.TFrame")
        status_area.grid(row=0, column=1, sticky="e")
        ttk.Label(status_area, text="Status:", style="Panel.TLabel").grid(row=0, column=0, sticky="e")
        self.status_label = tk.Label(status_area, textvariable=self.status, bg=self.PANEL, fg="#f3c969", font=("Segoe UI", 10, "bold"))
        self.status_label.grid(row=0, column=1, padx=(6, 0), sticky="w")
        ttk.Label(status_area, text="Latest model results", style="Panel.TLabel").grid(row=1, column=0, columnspan=2, sticky="e", pady=(7, 2))

        badges = ttk.Frame(top, style="Panel.TFrame")
        badges.grid(row=1, column=1, sticky="e", pady=(2, 0))
        self.detection_badge = self._badge(badges, "DETECTIONS: 0")
        self.detection_badge.grid(row=0, column=0, padx=2, pady=2)
        self.model_badge = self._badge(badges, "MODEL READY" if self.detector.is_ready else "MODEL MISSING", "#147fa4" if self.detector.is_ready else "#b93d3d")
        self.model_badge.grid(row=0, column=1, padx=2, pady=2)
        self.email_badge = self._badge(badges, "EMAIL READY" if AlertSystem.email_is_configured(self.receiver_email_value) else "EMAIL NOT CONFIGURED", "#147fa4" if AlertSystem.email_is_configured(self.receiver_email_value) else "#5e7182")
        self.email_badge.grid(row=1, column=0, columnspan=2, padx=2, pady=2)

        footer = ttk.Frame(top, style="Panel.TFrame")
        footer.grid(row=2, column=0, columnspan=2, sticky="e", pady=(7, 0))
        ttk.Label(footer, textvariable=self.activity, style="Panel.TLabel").pack(side=tk.LEFT, padx=8)
        ttk.Label(footer, textvariable=self.frames, style="Panel.TLabel").pack(side=tk.LEFT, padx=8)
        top.columnconfigure(0, weight=1)

        content = ttk.Frame(self.root)
        content.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 12))
        content.columnconfigure(0, weight=4)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(0, weight=1)

        feed = ttk.Frame(content, style="Panel.TFrame", padding=8)
        feed.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        ttk.Label(feed, text="▣  Live Feed", style="Section.TLabel").pack(anchor="w", pady=(0, 7))
        self.video_label = tk.Label(feed, text="No video source selected\n\nClick 'Load Video' or 'Use Camera'", bg="black", fg="white", font=("Segoe UI", 13), justify=tk.CENTER)
        self.video_label.pack(fill=tk.BOTH, expand=True)

        right = ttk.Frame(content)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        settings = ttk.Frame(right, style="Panel.TFrame", padding=10)
        settings.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(settings, text="⚙  Settings", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Label(settings, text="Confidence Threshold", style="Panel.TLabel").pack(anchor="w")
        self.conf_label = ttk.Label(settings, text=f"{self.confidence_threshold:.2f}", style="Panel.TLabel")
        self.conf_label.pack(anchor="e")
        ttk.Scale(settings, from_=0.10, to=0.95, variable=self.confidence, command=self._on_confidence_change).pack(fill=tk.X, pady=(0, 10))
        ttk.Label(settings, text="Alert Cooldown (sec)", style="Panel.TLabel").pack(anchor="w")
        ttk.Spinbox(settings, from_=1, to=300, textvariable=self.cooldown, width=8).pack(fill=tk.X, pady=(3, 10))
        ttk.Label(settings, text="Receiver Email", style="Panel.TLabel").pack(anchor="w")
        ttk.Entry(settings, textvariable=self.receiver_email).pack(fill=tk.X, pady=(3, 10))
        self._button(settings, "▣ Save Settings", self.save_settings, self.TEAL).pack(fill=tk.X)

        ttk.Label(settings, text="Current detections", style="Panel.TLabel").pack(anchor="w", pady=(10, 2))
        ttk.Label(settings, textvariable=self.detection_summary, style="Panel.TLabel", wraplength=230, justify=tk.LEFT).pack(fill=tk.X, anchor="w")

        log_panel = ttk.Frame(right, style="Panel.TFrame", padding=8)
        log_panel.grid(row=1, column=0, sticky="nsew")
        ttk.Label(log_panel, text="▣  Activity Log", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        body = ttk.Frame(log_panel, style="Panel.TFrame")
        body.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(body, wrap=tk.WORD, bg="#172735", fg="#dbe5ec", insertbackground="white", relief=tk.FLAT, font=("Consolas", 8), state=tk.DISABLED)
        scroll = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _button(self, parent, text, command, color):
        return tk.Button(parent, text=text, command=command, bg=color, fg="white", activebackground=color, activeforeground="white", relief=tk.FLAT, bd=0, padx=10, pady=9, cursor="hand2", font=("Segoe UI", 9, "bold"))

    def _badge(self, parent, text, color="#5e7182"):
        return tk.Label(parent, text=text, bg=color, fg="white", font=("Segoe UI", 8, "bold"), padx=7, pady=4)

    def log(self, message):
        stamp = time.strftime("%H:%M:%S")
        logger.info(message)
        if hasattr(self, "log_text"):
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"[{stamp}] {message}\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)

    def _on_confidence_change(self, value):
        self.confidence_threshold = float(value)
        self.conf_label.configure(text=f"{self.confidence_threshold:.2f}")

    def save_settings(self):
        try:
            cooldown = int(self.cooldown.get())
            if not 1 <= cooldown <= 300:
                raise ValueError
        except (ValueError, tk.TclError):
            messagebox.showerror("Invalid setting", "Cooldown must be a whole number from 1 to 300 seconds.", parent=self.root)
            return

        recipient = self.receiver_email.get().strip()
        self.receiver_email_value = recipient
        self.cooldown_seconds = cooldown
        self.alert_system.cooldown = float(cooldown)
        email_ready = AlertSystem.email_is_configured(recipient)
        self.email_badge.configure(text="EMAIL READY" if email_ready else "EMAIL NOT CONFIGURED", bg="#147fa4" if email_ready else "#5e7182")
        self.log(f"Settings saved: confidence={self.confidence_threshold:.2f}, cooldown={cooldown}s, recipient={'set' if recipient else 'not set'}")
        if not email_ready:
            messagebox.showwarning("Email settings", "Detection can run, but email alerts require EMAIL_SENDER and EMAIL_PASSWORD in .env and a receiver email.", parent=self.root)
        else:
            messagebox.showinfo("Settings", "Settings saved for this session.", parent=self.root)

    def load_video(self):
        path = filedialog.askopenfilename(title="Select a video", filetypes=[("Video files", "*.mp4 *.avi *.mov *.mkv *.wmv"), ("All files", "*.*")], parent=self.root)
        if not path:
            return
        self.stop_detection(clear_display=False)
        self.video_path = path
        self.source_kind = "video"
        self.log(f"Video selected: {path}")
        self._request_start()

    def use_camera(self):
        self.stop_detection(clear_display=False)
        self.video_path = None
        self.source_kind = "camera"
        self._request_start()

    def _request_start(self):
        self.pending_start = True
        self._try_pending_start()

    def _try_pending_start(self):
        if self.closing or not self.pending_start:
            return
        if self.worker_thread is not None and self.worker_thread.is_alive():
            self.root.after(50, self._try_pending_start)
            return
        self.pending_start = False
        self.start_detection()

    def start_detection(self):
        if self.closing:
            return
        if self.is_running:
            self.log("Detection is already running.")
            return
        if self.worker_thread is not None and self.worker_thread.is_alive():
            # A previous capture worker may still be releasing the camera.
            self.pending_start = True
            self.root.after(50, self._try_pending_start)
            return
        if not self.detector.is_ready:
            messagebox.showerror("Model unavailable", self.detector.load_error or "The YOLO model could not be loaded.", parent=self.root)
            return
        if self.source_kind is None:
            self.source_kind = "camera"
            self.video_path = None

        source = self.video_path if self.source_kind == "video" else 0
        if source is None:
            messagebox.showerror("Source error", "Select a video or choose Use Camera.", parent=self.root)
            return

        self.stop_event = threading.Event()
        self.is_running = True
        self.status.set("Starting source...")
        self.status_label.configure(fg="#f3c969")
        self.activity.set("RUNNING")
        self.email_warning_logged = False
        if not AlertSystem.email_is_configured(self.receiver_email_value):
            self.log("Email alerts are disabled until sender, app password, and receiver are configured.")
            self.email_warning_logged = True

        self.worker_thread = threading.Thread(target=self._capture_loop, args=(source, self.stop_event), daemon=True, name="SurveillanceCapture")
        self.worker_thread.start()
        self.log("Detection worker started.")

    def _capture_loop(self, source, stop_event):
        capture = None
        try:
            if source == 0 and hasattr(cv2, "CAP_DSHOW"):
                capture = cv2.VideoCapture(0, cv2.CAP_DSHOW)
                if not capture.isOpened():
                    capture.release()
                    capture = cv2.VideoCapture(0)
            else:
                capture = cv2.VideoCapture(source)

            if not capture.isOpened():
                self._publish_message(("error", "Could not open the selected video or camera."))
                return

            frame_count = 0
            self._publish_message(("started", "Video source opened."))
            while not stop_event.is_set():
                ok, frame = capture.read()
                if not ok:
                    if not stop_event.is_set():
                        self._publish_message(("ended", "Video ended or a frame could not be read."))
                    break

                annotated, detections = self.detector.process_frame(frame, self.confidence_threshold)
                frame_count += 1

                # Generic by design: use the class names actually supplied by best.pt.
                if AlertSystem.email_is_configured(self.receiver_email_value):
                    for detection in detections:
                        success, result_message = self.alert_system.trigger_alert(
                            self.receiver_email_value,
                            detection["class"],
                            detection["confidence"],
                            annotated,
                        )
                        if success:
                            self._publish_message(("alert", result_message))
                self._publish_message(("frame", annotated, detections, frame_count))
        except Exception as error:
            logger.exception("Detection worker failed.")
            self._publish_message(("error", f"Detection failed: {error}"))
        finally:
            if capture is not None:
                capture.release()
            self._publish_message(("worker_done", None))

    def _publish_message(self, message):
        """Keep the queue small and prioritize errors/status over stale frames."""
        try:
            self.messages.put_nowait(message)
            return
        except queue.Full:
            pass

        queued = []
        while True:
            try:
                queued.append(self.messages.get_nowait())
            except queue.Empty:
                break

        if message[0] == "frame":
            # Replace an older frame, but never evict status/error messages for it.
            frame_index = next((i for i, item in enumerate(queued) if item[0] == "frame"), None)
            if frame_index is None and len(queued) >= self.messages.maxsize:
                return
            if frame_index is not None:
                queued.pop(frame_index)
        else:
            # Important messages can evict a frame first; if none exists, evict oldest.
            frame_index = next((i for i, item in enumerate(queued) if item[0] == "frame"), None)
            queued.pop(frame_index if frame_index is not None else 0)

        for item in queued:
            try:
                self.messages.put_nowait(item)
            except queue.Full:
                break
        try:
            self.messages.put_nowait(message)
        except queue.Full:
            pass

    def _poll_worker_messages(self):
        if self.closing:
            return
        try:
            while True:
                message = self.messages.get_nowait()
                kind = message[0]
                if kind == "started":
                    self.status.set("Running")
                    self.status_label.configure(fg="#f3c969")
                    self.log(message[1])
                elif kind == "frame":
                    _, frame, detections, count = message
                    self.frame_count = count
                    self.frames.set(f"Frames: {count}")
                    self._show_frame(frame)
                    self._update_detection_status(detections)
                elif kind == "alert":
                    self.log(message[1])
                elif kind == "error":
                    self.is_running = False
                    self.status.set("Source/model error")
                    self.status_label.configure(fg="#ff7770")
                    self.activity.set("STANDBY")
                    self.log(message[1])
                    messagebox.showerror("Detection error", message[1], parent=self.root)
                elif kind == "ended":
                    self.is_running = False
                    self.status.set("Stopped")
                    self.status_label.configure(fg="#f3c969")
                    self.activity.set("STANDBY")
                    self.log(message[1])
                elif kind == "worker_done":
                    if self.is_running:
                        self.is_running = False
                        self.status.set("Stopped")
                        self.activity.set("STANDBY")
        except queue.Empty:
            pass

        self._poll_id = self.root.after(30, self._poll_worker_messages)

    def _show_frame(self, frame):
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        max_width = max(self.video_label.winfo_width(), 320)
        max_height = max(self.video_label.winfo_height(), 220)
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        image.thumbnail((max_width, max_height), resampling)
        self._photo = ImageTk.PhotoImage(image=image)
        self.video_label.configure(image=self._photo, text="")
        self.video_label.image = self._photo

    def _update_detection_status(self, detections):
        # Show both the predicted class and which independent model produced it.
        count = len(detections)
        self.detection_badge.configure(
            text=f"DETECTIONS: {count}",
            bg="#b93d3d" if count else "#5e7182",
        )

        model_labels = sorted({
            f"{item.get('model', 'model')}:{item.get('class', 'unknown')}"
            for item in detections
        })
        if model_labels:
            self.detection_summary.set(", ".join(model_labels))
            self.status.set(f"Detected {count} prediction(s)")
            self.status_label.configure(fg="#ff7770")
        else:
            self.detection_summary.set("No detections in the latest frame")
            self.status.set("Running")
            self.status_label.configure(fg="#f3c969")

    def stop_detection(self, clear_display=True):
        was_running = self.is_running
        self.is_running = False
        self.pending_start = False
        if self.stop_event is not None:
            self.stop_event.set()
        self.activity.set("STANDBY")
        if was_running:
            self.status.set("Stopping..." if self.worker_thread and self.worker_thread.is_alive() else "Stopped")
            self.log("Stop requested.")
        if clear_display:
            self.video_label.configure(image="", text="Detection stopped\n\nClick 'Load Video' or 'Use Camera'", bg="black", fg="white")
            self.video_label.image = None
            self._photo = None

    def on_close(self):
        if self.closing:
            return
        self.closing = True
        self.pending_start = False
        self.is_running = False
        if self.stop_event is not None:
            self.stop_event.set()
        self._close_started_at = time.monotonic()
        self.log("Closing requested; waiting briefly for the capture worker to stop.")
        self._finish_close()

    def _finish_close(self):
        worker_alive = self.worker_thread is not None and self.worker_thread.is_alive()
        # Do not block Tkinter waiting for a camera read; allow up to 2 seconds.
        if worker_alive and time.monotonic() - self._close_started_at < 2.0:
            self.root.after(50, self._finish_close)
            return
        try:
            if self._poll_id is not None:
                self.root.after_cancel(self._poll_id)
        except tk.TclError:
            pass
        self.root.destroy()


def run_app():
    root = tk.Tk()
    AppGUI(root)
    root.mainloop()
