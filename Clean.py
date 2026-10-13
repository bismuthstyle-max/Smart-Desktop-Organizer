import os
import sys
import time
import shutil
import sqlite3
import subprocess
import queue
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog
import customtkinter as ctk
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Try importing PDF text extraction safely
try:
    import pypdf
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

# Global Appearance Settings
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Universal Paths - Always stored safely on user's hard drive
USER_HOME = Path.home()
DESKTOP_PATH = USER_HOME / "Desktop"
DOWNLOADS_PATH = USER_HOME / "Downloads"
BASE_TARGET_DIR = USER_HOME / "Smart Desktop Organizer"
DB_FILE = BASE_TARGET_DIR / "organizer_memory.db"

# ==========================================
# Persistent Database & Learning Memory
# ==========================================
def init_db():
    """Initializes local SQLite database stored permanently on the computer."""
    BASE_TARGET_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS file_rules (
            keyword TEXT PRIMARY KEY,
            target_category TEXT,
            use_count INTEGER DEFAULT 1
        )
    ''')
    conn.commit()
    conn.close()

init_db()

def save_learned_rule(keyword, category):
    if not keyword or len(keyword) < 2:
        return
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO file_rules (keyword, target_category, use_count)
        VALUES (?, ?, 1)
        ON CONFLICT(keyword) DO UPDATE SET use_count = use_count + 1, target_category = ?
    ''', (keyword.lower(), category, category))
    conn.commit()
    conn.close()

def get_learned_category(full_text):
    if not DB_FILE.exists():
        return None
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT keyword, target_category FROM file_rules ORDER BY use_count DESC")
    rules = cursor.fetchall()
    conn.close()

    full_text_lower = full_text.lower()
    for kw, cat in rules:
        if kw in full_text_lower:
            return cat
    return None

def get_existing_folders(base_path=BASE_TARGET_DIR, prefix=""):
    """Scans and lists real physical user directories."""
    BASE_TARGET_DIR.mkdir(parents=True, exist_ok=True)
    folder_list = []
    try:
        for item in base_path.iterdir():
            if item.is_dir() and not item.name.startswith("."):
                rel_path = f"{prefix}{item.name}"
                folder_list.append(rel_path)
                if prefix.count('/') < 2:
                    folder_list.extend(get_existing_folders(item, prefix=f"{rel_path}/"))
    except Exception:
        pass
    return sorted(folder_list)

# ==========================================
# Safe Extraction & Context Matching
# ==========================================
def extract_text_from_pdf(file_path):
    if not HAS_PYPDF or file_path.suffix.lower() != '.pdf':
        return ""
    try:
        reader = pypdf.PdfReader(file_path)
        return "".join([p.extract_text() or "" for p in reader.pages[:2]]).lower()
    except Exception:
        return ""

def predict_folder_for_file(file_path):
    file_name = file_path.name.lower()
    ext = file_path.suffix.lower().replace(".", "")
    pdf_text = extract_text_from_pdf(file_path)
    combined_text = f"{file_name} {ext} {pdf_text}"

    learned_cat = get_learned_category(combined_text)
    if learned_cat:
        return learned_cat

    existing_folders = get_existing_folders()
    for folder in existing_folders:
        folder_leaf = folder.split('/')[-1].lower()
        if folder_leaf in combined_text:
            return folder

    return None

# ==========================================
# Human-in-the-Loop Confirmation Window
# ==========================================
class QuickPromptWindow(ctk.CTkToplevel):
    def __init__(self, file_path, suggested_category, app_ref, on_close_callback):
        super().__init__()
        self.file_path = file_path
        self.app_ref = app_ref
        self.on_close_callback = on_close_callback

        self.title("Smart File Classifier")
        self.geometry("480x360")
        self.resizable(True, True)
        self.attributes("-topmost", True)
        self.configure(fg_color="#1E1E2E")

        header_card = ctk.CTkFrame(self, fg_color="#2A2B3D", corner_radius=12)
        header_card.pack(padx=20, pady=(20, 10), fill="x")

        ctk.CTkLabel(
            header_card, 
            text="⚡ New File Detected", 
            font=("Segoe UI", 16, "bold"), 
            text_color="#6366F1"
        ).pack(anchor="w", padx=15, pady=(12, 2))

        ctk.CTkLabel(
            header_card, 
            text=f"📄 {file_path.name}", 
            font=("Segoe UI", 12), 
            text_color="#E2E8F0",
            wraplength=410,
            justify="left"
        ).pack(anchor="w", padx=15, pady=(0, 12))

        self.existing_folders = get_existing_folders()
        options = self.existing_folders + ["📁 Create Folder / Subfolder..."]

        if suggested_category and suggested_category in self.existing_folders:
            default_val = suggested_category
            lbl_text = "🎯 Suggested Location:"
        elif self.existing_folders:
            default_val = self.existing_folders[0]
            lbl_text = "📂 Select Destination Folder:"
        else:
            default_val = "📁 Create Folder / Subfolder..."
            lbl_text = "✨ Create your first folder:"

        ctk.CTkLabel(self, text=lbl_text, font=("Segoe UI", 11, "bold"), text_color="#94A3B8").pack(anchor="w", padx=25, pady=(10, 4))

        self.selected_category = ctk.StringVar(value=default_val)
        self.combo = ctk.CTkOptionMenu(
            self, 
            variable=self.selected_category, 
            values=options, 
            height=38,
            fg_color="#334155",
            button_color="#475569",
            button_hover_color="#64748B",
            dropdown_fg_color="#1E293B",
            font=("Segoe UI", 12),
            command=self.on_category_select
        )
        self.combo.pack(padx=20, pady=5, fill="x")

        btns_frame = ctk.CTkFrame(self, fg_color="transparent")
        btns_frame.pack(padx=20, pady=(25, 0), fill="x")

        ctk.CTkButton(
            btns_frame, 
            text="Confirm & Move", 
            command=self.confirm_move, 
            fg_color="#10B981", 
            hover_color="#059669", 
            font=("Segoe UI", 12, "bold"),
            height=40,
            corner_radius=8
        ).pack(side="left", fill="x", expand=True, padx=(0, 5))

        ctk.CTkButton(
            btns_frame, 
            text="Keep In Place", 
            command=self.skip_file, 
            fg_color="#475569", 
            hover_color="#334155", 
            font=("Segoe UI", 12),
            height=40,
            corner_radius=8
        ).pack(side="right", fill="x", expand=True, padx=(5, 0))

        self.protocol("WM_DELETE_WINDOW", self.skip_file)

    def on_category_select(self, choice):
        if choice == "📁 Create Folder / Subfolder...":
            new_folder = simpledialog.askstring(
                "Create Folder", 
                "Enter new folder or subfolder path (e.g. 'Work/Projects'):", 
                parent=self
            )
            if new_folder and new_folder.strip():
                clean_name = new_folder.strip()
                if clean_name not in self.existing_folders:
                    self.existing_folders.append(clean_name)
                    updated_options = self.existing_folders + ["📁 Create Folder / Subfolder..."]
                    self.combo.configure(values=updated_options)
                self.selected_category.set(clean_name)
            else:
                fallback = self.existing_folders[0] if self.existing_folders else "📁 Create Folder / Subfolder..."
                self.selected_category.set(fallback)

    def confirm_move(self):
        cat = self.selected_category.get().strip()
        if cat == "📁 Create Folder / Subfolder...":
            new_folder = simpledialog.askstring("New Folder", "Enter folder path:", parent=self)
            if new_folder and new_folder.strip():
                cat = new_folder.strip()
            else:
                return

        target_dir = BASE_TARGET_DIR / cat
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            dest_path = target_dir / self.file_path.name
            shutil.move(str(self.file_path), str(dest_path))

            prefix = self.file_path.stem.split('_')[0].split('-')[0]
            save_learned_rule(prefix, cat)
            self.app_ref.log_activity(f"Moved: {self.file_path.name} ➔ {cat}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not move file: {e}")

        self.close_window()

    def skip_file(self):
        self.app_ref.log_activity(f"Skipped file: {self.file_path.name} (Kept in place)")
        self.close_window()

    def close_window(self):
        if self.on_close_callback:
            self.on_close_callback()
        self.destroy()

# ==========================================
# File Observer with Safe Queue
# ==========================================
class UniversalFileWatcher(FileSystemEventHandler):
    def __init__(self, app_root):
        self.app_root = app_root
        self.processed = set()

    def on_created(self, event):
        if event.is_directory:
            return
        path = Path(event.src_path)

        if path.name.startswith("~$") or path.name.startswith(".") or path.suffix in ['.tmp', '.crdownload', '.opdownload', '.part']:
            return

        max_wait = 10
        file_size_prev = -1
        for _ in range(max_wait):
            if not path.exists():
                return
            try:
                current_size = path.stat().st_size
                if current_size == file_size_prev and current_size > 0:
                    break
                file_size_prev = current_size
            except Exception:
                pass
            time.sleep(0.5)

        if path.exists() and path not in self.processed:
            self.processed.add(path)
            self.app_root.file_queue.put(path)
            self.app_root.check_queue()

# ==========================================
# Main Dashboard Panel
# ==========================================
class UniversalOrganizerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Smart Desktop Organizer Pro")
        self.geometry("920x600")
        self.minsize(700, 500)
        self.resizable(True, True)
        self.configure(fg_color="#0F172A")

        self.file_queue = queue.Queue()
        self.is_popup_open = False

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---- Sidebar Control Frame ----
        self.sidebar_frame = ctk.CTkFrame(self, width=270, corner_radius=0, fg_color="#1E293B")
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")

        ctk.CTkLabel(
            self.sidebar_frame, 
            text="⚙️ CONTROL PANEL", 
            font=("Segoe UI", 15, "bold"),
            text_color="#6366F1"
        ).pack(pady=(25, 15), padx=20, anchor="w")

        # Sidebar Buttons
        self.create_side_button("📂  Open Target Directory", self.open_base_dir, "#2563EB", "#1D4ED8")
        self.create_side_button("➕  Create Folder / Subfolder", self.add_new_category, "#10B981", "#059669")
        self.create_side_button("📥  Import Existing Folder", self.import_existing_folder, "#0EA5E9", "#0284C7")
        self.create_side_button("📋  Explore Hierarchy", self.show_categories, "#475563", "#334155")
        self.create_side_button("🧠  View Learned AI Memory", self.show_learned_rules, "#8B5CF6", "#7C3AED")

        # ---- Main Content Area ----
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=25, pady=25)

        header_card = ctk.CTkFrame(self.main_frame, fg_color="#1E293B", corner_radius=12)
        header_card.pack(fill="x", pady=(0, 15))

        ctk.CTkLabel(
            header_card, 
            text="Smart Desktop AI Pro", 
            font=("Segoe UI", 20, "bold"),
            text_color="#F8FAFC"
        ).pack(anchor="w", padx=20, pady=(15, 2))

        ctk.CTkLabel(
            header_card, 
            text="🟢 Real-Time Monitoring  |  🔒 100% Local, Safe & Permanent Storage", 
            font=("Segoe UI", 11), 
            text_color="#34D399"
        ).pack(anchor="w", padx=20, pady=(0, 15))

        ctk.CTkLabel(
            self.main_frame, 
            text="Live Activity Stream:", 
            font=("Segoe UI", 13, "bold"),
            text_color="#CBD5E1"
        ).pack(anchor="w", pady=(5, 8))

        self.log_box = ctk.CTkTextbox(
            self.main_frame, 
            font=("Consolas", 12),
            fg_color="#1E293B",
            text_color="#38BDF8",
            corner_radius=10,
            border_width=1,
            border_color="#334155"
        )
        self.log_box.pack(fill="both", expand=True)
        self.log_box.insert("1.0", "System ready. All user data is preserved permanently on your drive...\n")
        self.log_box.configure(state="disabled")

        # Start File Observer
        self.observer = Observer()
        handler = UniversalFileWatcher(self)

        if DESKTOP_PATH.exists():
            self.observer.schedule(handler, str(DESKTOP_PATH), recursive=False)
        if DOWNLOADS_PATH.exists():
            self.observer.schedule(handler, str(DOWNLOADS_PATH), recursive=False)

        self.observer.start()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_side_button(self, text, command, color, hover_color):
        btn = ctk.CTkButton(
            self.sidebar_frame, 
            text=text, 
            command=command, 
            fg_color=color, 
            hover_color=hover_color, 
            font=("Segoe UI", 12, "bold"),
            height=40,
            corner_radius=8,
            anchor="w"
        )
        btn.pack(fill="x", padx=20, pady=7)

    def check_queue(self):
        if not self.is_popup_open and not self.file_queue.empty():
            self.is_popup_open = True
            file_path = self.file_queue.get()
            suggested_cat = predict_folder_for_file(file_path)
            QuickPromptWindow(file_path, suggested_cat, self, self.on_popup_closed)

    def on_popup_closed(self):
        self.is_popup_open = False
        if not self.file_queue.empty():
            self.after(100, self.check_queue)

    def log_activity(self, message):
        self.log_box.configure(state="normal")
        timestamp = time.strftime("[%H:%M:%S]")
        self.log_box.insert("end", f"{timestamp} • {message}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def open_base_dir(self):
        BASE_TARGET_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if sys.platform == "win32":
                os.startfile(str(BASE_TARGET_DIR))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(BASE_TARGET_DIR)])
            else:
                subprocess.run(["xdg-open", str(BASE_TARGET_DIR)])
        except Exception as e:
            messagebox.showerror("Error", f"Could not open directory: {e}")

    def add_new_category(self):
        new_cat = simpledialog.askstring("New Folder", "Enter folder name or path (e.g. 'Work/Invoices'):")
        if new_cat and new_cat.strip():
            folder_path = BASE_TARGET_DIR / new_cat.strip()
            folder_path.mkdir(parents=True, exist_ok=True)
            self.log_activity(f"Created location: '{new_cat.strip()}'")
            messagebox.showinfo("Success", f"Folder '{new_cat.strip()}' created successfully!")

    def import_existing_folder(self):
        selected = filedialog.askdirectory(title="Select Existing Folder to Import")
        if selected:
            folder_name = Path(selected).name
            target = BASE_TARGET_DIR / folder_name
            try:
                if not target.exists():
                    shutil.copytree(selected, target)
                    self.log_activity(f"Imported folder: '{folder_name}'")
                    messagebox.showinfo("Success", f"Folder '{folder_name}' safely copied to target directory!")
                else:
                    messagebox.showinfo("Notice", "Folder with this name already exists in target directory.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to import folder: {e}")

    def show_categories(self):
        folders = get_existing_folders()
        if not folders:
            messagebox.showinfo("Folder Hierarchy", "No user folders created yet.")
            return
        cats_str = "\n".join([f"📁 {folder}" for folder in folders])
        messagebox.showinfo("Current Folder Structure", f"Stored Folders:\n\n{cats_str}")

    def show_learned_rules(self):
        try:
            if not DB_FILE.exists():
                messagebox.showinfo("AI System Memory", "No rules learned yet.")
                return
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute("SELECT keyword, target_category, use_count FROM file_rules")
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                messagebox.showinfo("AI System Memory", "No custom rules learned yet.")
                return

            rules_str = "\n".join([f"• Pattern: '{row[0]}' ➔ Folder: '{row[1]}' ({row[2]} times)" for row in rows])
            messagebox.showinfo("Auto-Learned Memory Rules", f"Saved AI Memory Rules:\n\n{rules_str}")
        except Exception as e:
            messagebox.showerror("Error", f"Could not read memory database: {e}")

    def on_closing(self):
        self.observer.stop()
        self.observer.join()
        self.destroy()

if __name__ == "__main__":
    app = UniversalOrganizerApp()
    app.mainloop()