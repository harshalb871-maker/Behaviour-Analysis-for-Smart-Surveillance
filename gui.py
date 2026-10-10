import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk
import cv2
import os
from datetime import datetime

from detection import ObjectDetector
from logger import logger


class AppGUI:
    """Surveillance dashboard styled after the supplied screenshot."""

    BG = "#24384a"
    PANEL = "#2d4357"
    GREEN = "#22a879"
    RED = "#e74c3c"
    BLUE = "#2798d0"
    PURPLE = "#9658b8"
    TEAL = "#169f8a"

    def __init__(self, root):
        self.root = root
        self.root.title("Surveillance Detection System")
        self.root.geometry("1180x760")
        self.root.minsize(900, 620)
        self.root.configure(bg=self.BG)

        self.detector = ObjectDetector()
        self.cap = None
        self.is_running = False
        self.source_kind = None
        self.video_path = None
        self.frame_count = 0
        self.confidence = tk.DoubleVar(value=0.70)
        self.cooldown = tk.IntVar(value=10)
        self.receiver_email = tk.StringVar()
        self.status = tk.StringVar(value="Ready")
        self.activity = tk.StringVar(value="STANDBY")
        self.frames = tk.StringVar(value="Frames: 0")
        self._photo = None

        self._style()
        self.setup_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.log("Surveillance Detection System ready.")

    def _style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=self.BG)
        style.configure("Panel.TFrame", background=self.PANEL)
        style.configure("TLabel", background=self.BG, foreground="#edf3f7",
                        font=("Segoe UI", 10))
        style.configure("Panel.TLabel", background=self.PANEL, foreground="#edf3f7",
                        font=("Segoe UI", 10))
        style.configure("Title.TLabel", background=self.BG, foreground="#edf3f7",
                        font=("Segoe UI", 19, "bold"))
        style.configure("Section.TLabel", background=self.PANEL, foreground="#edf3f7",
                        font=("Segoe UI", 11, "bold"))
        style.configure("TButton", font=("Segoe UI", 9, "bold"), padding=7)
        style.configure("TEntry", fieldbackground="#f3f6f8", foreground="#172735")
        style.configure("TSpinbox", fieldbackground="#f3f6f8", foreground="#172735")
        style.configure("Horizontal.TScale", background=self.PANEL, troughcolor="#d6dde2")

    def setup_ui(self):
        header = ttk.Frame(self.root)
        header.pack(fill=tk.X, padx=14, pady=(12, 8))
        ttk.Label(header, text="🔒  Surveillance Detection System",
                  style="Title.TLabel").pack()

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
        self.status_label = tk.Label(status_area, textvariable=self.status, bg=self.PANEL,
                                     fg="#f3c969", font=("Segoe UI", 10, "bold"))
        self.status_label.grid(row=0, column=1, padx=(6, 0), sticky="w")
        ttk.Label(status_area, text="Current Activity Status", style="Panel.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="e", pady=(7, 2))

        badges = ttk.Frame(top, style="Panel.TFrame")
        badges.grid(row=1, column=1, sticky="e", pady=(2, 0))
        self.weapon_badge = self._badge(badges, "WEAPON")
        self.weapon_badge.grid(row=0, column=0, padx=2, pady=2)
        self.fight_badge = self._badge(badges, "FIGHTING")
        self.fight_badge.grid(row=0, column=1, padx=2, pady=2)
        self.running_badge = self._badge(badges, "RUNNING")
        self.running_badge.grid(row=0, column=2, padx=2, pady=2)
        self.fall_badge = self._badge(badges, "FALLDOWN")
        self.fall_badge.grid(row=1, column=0, padx=2, pady=2)
        self.normal_badge = self._badge(badges, "NORMAL")
        self.normal_badge.grid(row=1, column=1, padx=2, pady=2)
        self.email_badge = self._badge(badges, "EMAIL READY", "#147fa4")
        self.email_badge.grid(row=1, column=2, padx=2, pady=2)

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
        self.video_label = tk.Label(
            feed, text="No video source selected\n\nClick 'Load Video' or 'Use Camera'",
            bg="black", fg="white", font=("Segoe UI", 13), justify=tk.CENTER
        )
        self.video_label.pack(fill=tk.BOTH, expand=True)

        right = ttk.Frame(content)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        settings = ttk.Frame(right, style="Panel.TFrame", padding=10)
        settings.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Label(settings, text="⚙  Settings", style="Section.TLabel").pack(anchor="w", pady=(0, 10))
        ttk.Label(settings, text="Confidence Threshold", style="Panel.TLabel").pack(anchor="w")
        self.conf_label = ttk.Label(settings, text="0.70", style="Panel.TLabel")
        self.conf_label.pack(anchor="e")
        ttk.Scale(settings, from_=0.10, to=0.95, variable=self.confidence,
                  command=lambda _v: self.conf_label.config(text=f"{self.confidence.get():.2f}")).pack(fill=tk.X, pady=(0, 10))
        ttk.Label(settings, text="Alert Cooldown (sec)", style="Panel.TLabel").pack(anchor="w")
        ttk.Spinbox(settings, from_=1, to=300, textvariable=self.cooldown, width=8).pack(fill=tk.X, pady=(3, 10))
        ttk.Label(settings, text="Receiver Email", style="Panel.TLabel").pack(anchor="w")
        ttk.Entry(settings, textvariable=self.receiver_email).pack(fill=tk.X, pady=(3, 10))
        self._button(settings, "▣ Save Settings", self.save_settings, self.TEAL).pack(fill=tk.X)

        log_panel = ttk.Frame(right, style="Panel.TFrame", padding=8)
        log_panel.grid(row=1, column=0, sticky="nsew")
        ttk.Label(log_panel, text="▣  Detection Log", style="Section.TLabel").pack(anchor="w", pady=(0, 6))
        body = ttk.Frame(log_panel, style="Panel.TFrame")
        body.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(body, wrap=tk.WORD, bg="#172735", fg="#dbe5ec",
                                insertbackground="white", relief=tk.FLAT,
                                font=("Consolas", 8), state=tk.DISABLED)
        scroll = ttk.Scrollbar(body, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _button(self, parent, text, command, color):
        return tk.Button(parent, text=text, command=command, bg=color, fg="white",
                         activebackground=color, activeforeground="white", relief=tk.FLAT,
                         bd=0, padx=10, pady=9, cursor="hand2",
                         font=("Segoe UI", 9, "bold"))

    def _badge(self, parent, text, color="#5e7182"):
        return tk.Label(parent, text=text, bg=color, fg="white",
                        font=("Segoe UI", 8, "bold"), padx=7, pady=4)

    def log(self, message):
        stamp = datetime.now().strftime("%H:%M:%S")
        try:
            logger.info(message)
        except Exception:
            pass
        if hasattr(self, "log_text"):
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, f"[{stamp}] {message}\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)

    def save_settings(self):
        try:
            if int(self.cooldown.get()) < 1:
                raise ValueError
        except (ValueError, tk.TclError):
            messagebox.showerror("Invalid setting", "Cooldown must be a whole number of at least 1 second.")
            return
        self.log(f"Settings saved: confidence={self.confidence.get():.2f}, cooldown={self.cooldown.get()}s, receiver={self.receiver_email.get() or 'not set'}")
        messagebox.showinfo("Settings", "Settings saved for this session.")

    def load_video(self):
        path = filedialog.askopenfilename(
            title="Select a video",
            filetypes=[("Video files", "*.mp4 *.avi *.mov *.mkv"), ("All files", "*.*")]
        )
        if not path:
            return
        self.stop_detection()
        self.video_path = path
        self.source_kind = "video"
        self.log(f"Video selected: {os.path.basename(path)}")
        self.start_detection()

    def use_camera(self):
        self.stop_detection()
        self.video_path = None
        self.source_kind = "camera"
        self.start_detection()

    def start_detection(self):
        if self.is_running:
            self.log("Detection is already running.")
            return
        if self.source_kind is None:
            self.source_kind = "camera"
        source = self.video_path if self.source_kind == "video" else 0
        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            self.cap.release()
            self.cap = None
            self.status.set("Source unavailable")
            self.activity.set("STANDBY")
            self.log("Could not open video source.")
            messagebox.showerror("Source error", "Could not open the selected video or camera.")
            return
        self.is_running = True
        self.status.set("Running")
        self.status_label.configure(fg="#f3c969")
        self.activity.set("RUNNING")
        self.log("Detection started.")
        self.update_frame()

    def stop_detection(self):
        was_running = self.is_running
        self.is_running = False
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self.activity.set("STANDBY")
        if was_running:
            self.status.set("Stopped")
            self.log("Detection stopped.")
        self.video_label.configure(image="", text="No video source selected\n\nClick 'Load Video' or 'Use Camera'", bg="black", fg="white")
        self.video_label.image = None

    def update_frame(self):
        if not self.is_running or self.cap is None:
            return
        ok, frame = self.cap.read()
        if not ok:
            self.log("Video ended or frame could not be read.")
            self.stop_detection()
            return

        self.frame_count += 1
        self.frames.set(f"Frames: {self.frame_count}")
        processed = frame
        try:
            processed, detections = self.detector.process_frame(frame)
            self._update_badges(detections)
        except Exception as exc:
            logger.exception("Frame processing failed")
            self.log(f"Detection error: {exc}")

        rgb = cv2.cvtColor(processed, cv2.COLOR_BGR2RGB)
        image = Image.fromarray(rgb)
        max_w = max(self.video_label.winfo_width(), 320)
        max_h = max(self.video_label.winfo_height(), 220)
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        image.thumbnail((max_w, max_h), resampling)
        self._photo = ImageTk.PhotoImage(image=image)
        self.video_label.configure(image=self._photo, text="")
        self.video_label.image = self._photo
        self.root.after(20, self.update_frame)

    def _update_badges(self, detections):
        labels = []
        if isinstance(detections, (list, tuple)):
            for item in detections:
                if isinstance(item, str):
                    labels.append(item.lower())
                elif isinstance(item, dict):
                    labels.append(str(item.get("class", item.get("name", ""))).lower())
        weapon = any(any(word in label for word in ("weapon", "gun", "knife")) for label in labels)
        fighting = any(any(word in label for word in ("fight", "violence")) for label in labels)
        self.weapon_badge.configure(bg="#b93d3d" if weapon else "#5e7182")
        self.fight_badge.configure(bg="#b93d3d" if fighting else "#5e7182")
        if weapon or fighting:
            self.status.set("Alert detected")
            self.status_label.configure(fg="#ff7770")
        else:
            self.status.set("Running")
            self.status_label.configure(fg="#f3c969")

    def on_close(self):
        self.is_running = False
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        self.root.destroy()


def run_app():
    root = tk.Tk()
    AppGUI(root)
    root.mainloop()