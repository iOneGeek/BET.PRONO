"""Widget Windows autonome pour consulter BET.PRONO depuis le bureau.

Ce fichier n'utilise que la bibliothèque standard de Python. Il ne conserve jamais
le mot de passe : la session API reste uniquement en mémoire pendant l'exécution.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections import defaultdict
from http.cookiejar import CookieJar
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog


APP_NAME = "BET.PRONO Widget"
WIDGET_VERSION = "V2.5.0"
CONFIG_PATH = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME / "config.json"
BRAND_IMAGE_NAME = "bet-prono-widget-logo.png"
BRAND_IMAGE_PATH = CONFIG_PATH.parent / BRAND_IMAGE_NAME
BUNDLED_BRAND_IMAGE_PATH = Path(__file__).with_name(BRAND_IMAGE_NAME)
BRAND_IMAGE_URL = f"/static/downloads/{BRAND_IMAGE_NAME}"
BRAND_ICON_NAME = "bet-prono-widget-logo.ico"
BRAND_ICON_PATH = CONFIG_PATH.parent / BRAND_ICON_NAME
BUNDLED_BRAND_ICON_PATH = Path(__file__).with_name(BRAND_ICON_NAME)
BRAND_ICON_URL = f"/static/downloads/{BRAND_ICON_NAME}"
DEFAULT_SITE_URL = "https://bet-prono.onrender.com"
BG = "#111827"
PANEL = "#1f2937"
PANEL_ALT = "#273449"
HEADER = "#0b1220"
LINE = "#334155"
TEXT = "#f9fafb"
MUTED = "#a9b4c6"
ACCENT = "#f97316"
ACCENT_DARK = "#c2410c"
GOOD = "#4ade80"
BAD = "#fb7185"


def as_number(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def date_of(bet: dict) -> dt.date | None:
    value = str(bet.get("d", ""))[:10]
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def profit_of(bet: dict) -> float:
    stake = as_number(bet.get("s"))
    odds = as_number(bet.get("o"))
    bonus = as_number(bet.get("b"))
    if bet.get("r") == "won":
        return stake * (odds - 1) + bonus
    if bet.get("r") == "lost":
        return -stake
    return 0.0


def balance_delta(bet: dict) -> float:
    if bet.get("r") == "wd":
        return -as_number(bet.get("s"))
    return profit_of(bet)


def compute_metrics(
    bets: list[dict], initial_bankroll: object, period_days: int | None, today: dt.date | None = None
) -> dict:
    """Calcule les quatre indicateurs du widget depuis les mêmes données que le site."""
    today = today or dt.date.today()
    cutoff = today - dt.timedelta(days=period_days - 1) if period_days else None
    all_bets = sorted(bets, key=lambda bet: (str(bet.get("d", "")), as_number(bet.get("id"))))
    visible = [
        bet
        for bet in all_bets
        if bet.get("r") != "wd" and (cutoff is None or (date_of(bet) and date_of(bet) >= cutoff))
    ]
    settled = [bet for bet in visible if bet.get("r") in {"won", "lost", "void"}]
    decisive = [bet for bet in settled if bet.get("r") in {"won", "lost"}]
    staked = sum(as_number(bet.get("s")) for bet in decisive)
    profit = sum(profit_of(bet) for bet in settled)
    wins = sum(bet.get("r") == "won" for bet in decisive)

    sports: dict[str, float] = defaultdict(float)
    for bet in settled:
        sports[str(bet.get("sp") or "Autre")] += profit_of(bet)

    before_period = [
        bet
        for bet in all_bets
        if cutoff and (date_of(bet) and date_of(bet) < cutoff)
    ]
    curve_bets = [
        bet
        for bet in all_bets
        if (cutoff is None or (date_of(bet) and date_of(bet) >= cutoff))
        and bet.get("r") in {"won", "lost", "void", "wd"}
    ]
    curve_balance = as_number(initial_bankroll) + sum(balance_delta(bet) for bet in before_period)
    curve = [curve_balance]
    for bet in curve_bets:
        curve_balance += balance_delta(bet)
        curve.append(curve_balance)

    return {
        "bankroll": as_number(initial_bankroll) + sum(balance_delta(bet) for bet in all_bets),
        "profit": profit,
        "roi": (profit / staked * 100) if staked else None,
        "win_rate": (wins / len(decisive) * 100) if decisive else None,
        "settled": len(settled),
        "pending": sum(bet.get("r") == "pending" for bet in visible),
        "wins": wins,
        "losses": sum(bet.get("r") == "lost" for bet in decisive),
        "decisive": len(decisive),
        "staked": staked,
        "sports": sorted(sports.items(), key=lambda item: item[1], reverse=True),
        "curve": curve,
    }


def eur(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.2f} €".replace(",", " ").replace(".", ",")


def percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f} %".replace(".", ",")


class BetPronoApi:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def _url(self, path: str) -> str:
        return urllib.parse.urljoin(self.base_url + "/", path.lstrip("/"))

    def request(self, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self._url(path),
            data=data,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        try:
            with self.opener.open(request, timeout=12) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read().decode("utf-8")).get("error")
            except (json.JSONDecodeError, UnicodeDecodeError):
                detail = None
            if error.code == 401:
                raise RuntimeError("Connecte-toi d’abord à ton compte BET.PRONO.") from error
            raise RuntimeError(detail or f"Erreur BET.PRONO ({error.code}).") from error
        except urllib.error.URLError as error:
            raise RuntimeError("Adresse introuvable. Vérifie que BET.PRONO est ouvert et que son adresse est correcte.") from error

    def login(self, username: str, password: str) -> None:
        self.request("api/login", {"username": username, "password": password})

    def pair(self, code: str) -> None:
        self.request("api/widget/pair", {"code": code})

    def bets(self) -> dict:
        return self.request("api/bets")


class BetPronoWidget(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.geometry("480x860+48+48")
        self.client: BetPronoApi | None = None
        self.base_url = self._load_url()
        self.period_days: int | None = 30
        self.period_buttons: dict[int | None, tk.Button] = {}
        self._drag_origin: tuple[int, int] | None = None
        self._sparkline_values: list[float] = []
        self._sparkline_progress = 1.0
        self._sparkline_job: str | None = None
        self._brand_image_full: tk.PhotoImage | None = None
        self._brand_image: tk.PhotoImage | None = None
        self.metric_details: dict[str, tk.Label] = {}

        self._build()
        self.after(80, self._load_brand_image)
        self._set_status("Connecte ton compte pour afficher tes statistiques.")

    def _build(self) -> None:
        header = tk.Frame(self, bg=HEADER, height=88)
        header.pack(fill="x")
        header.pack_propagate(False)
        for widget in (header,):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)

        accent = tk.Frame(header, bg=ACCENT, width=6)
        accent.pack(side="left", fill="y")
        brand = tk.Frame(header, bg=HEADER)
        brand.pack(side="left", fill="both", expand=True, padx=(14, 0), pady=10)
        self.brand_mark = tk.Label(brand, text="🦊", bg=HEADER, fg=ACCENT, font=("Segoe UI Emoji", 30), width=2)
        self.brand_mark.pack(side="left", padx=(0, 10))
        brand_copy = tk.Frame(brand, bg=HEADER)
        brand_copy.pack(side="left", fill="y")
        tk.Label(brand_copy, text="BET.PRONO", bg=HEADER, fg=TEXT, font=("Segoe UI", 17, "bold")).pack(anchor="w", pady=(3, 0))
        tk.Label(brand_copy, text=f"WIDGET BUREAU • {WIDGET_VERSION}", bg=HEADER, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(1, 0))
        close = tk.Button(header, text="×", command=self.destroy, bg=HEADER, fg=MUTED, bd=0, font=("Segoe UI", 18), activebackground=HEADER, activeforeground=TEXT, cursor="hand2")
        close.pack(side="right", padx=(6, 10))
        self.connection_badge = tk.Label(header, text="● HORS LIGNE", bg="#172235", fg=MUTED, font=("Segoe UI", 8, "bold"), padx=10, pady=5)
        self.connection_badge.pack(side="right", padx=(0, 2), pady=22)

        periods = tk.Frame(self, bg=BG)
        periods.pack(fill="x", padx=16, pady=(13, 4))
        tk.Label(periods, text="PÉRIODE", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 11))
        for label, days in (("7 jours", 7), ("30 jours", 30), ("90 jours", 90), ("Tout", None)):
            button = tk.Button(periods, text=label, command=lambda value=days: self._set_period(value), relief="flat", bd=0, padx=11, pady=6, font=("Segoe UI", 9, "bold"), cursor="hand2")
            button.pack(side="left", padx=(0, 5))
            self.period_buttons[days] = button
        self._paint_periods()

        cards = tk.Frame(self, bg=BG)
        cards.pack(fill="x", padx=16)
        self.bankroll = self._metric(cards, "BANKROLL", "—", 0, 0, "#38bdf8", "bankroll", "◉")
        self.profit = self._metric(cards, "BÉNÉFICE", "—", 0, 1, GOOD, "profit", "▥")
        self.roi = self._metric(cards, "ROI", "—", 1, 0, ACCENT, "roi", "%")
        self.win_rate = self._metric(cards, "RÉUSSITE", "—", 1, 1, "#a78bfa", "win_rate", "◎")

        chart_box = tk.Frame(self, bg=PANEL, highlightbackground="#35516d", highlightthickness=1)
        chart_box.pack(fill="x", padx=16, pady=(8, 7))
        chart_head = tk.Frame(chart_box, bg=PANEL)
        chart_head.pack(fill="x", padx=13, pady=(10, 0))
        tk.Label(chart_head, text="↗  ÉVOLUTION DE LA BANKROLL", bg=PANEL, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(side="left")
        self.chart_value = tk.Label(chart_head, text="—", bg=PANEL, fg=GOOD, font=("Segoe UI", 12, "bold"))
        self.chart_value.pack(side="right")
        self.sparkline = tk.Canvas(chart_box, height=132, bg=PANEL, highlightthickness=0, bd=0)
        self.sparkline.pack(fill="x", padx=7, pady=(4, 0))
        self.sparkline.bind("<Configure>", self._redraw_sparkline)
        self.chart_caption = tk.Label(chart_box, text="Connecte ton compte pour voir ta courbe.", bg=PANEL, fg=MUTED, font=("Segoe UI", 8), anchor="w")
        self.chart_caption.pack(fill="x", padx=13, pady=(0, 10))

        summary_box = tk.Frame(self, bg="#142238", highlightbackground="#263b55", highlightthickness=1)
        summary_box.pack(fill="x", padx=16, pady=(0, 7))
        tk.Label(summary_box, text="BILAN DE PÉRIODE", bg="#142238", fg=MUTED, font=("Segoe UI", 8, "bold")).pack(side="left", padx=12, pady=9)
        self.summary = tk.Label(summary_box, text="Aucune statistique disponible", bg="#142238", fg=TEXT, font=("Segoe UI", 8, "bold"), anchor="e")
        self.summary.pack(side="right", padx=12)

        sport_box = tk.Frame(self, bg=PANEL, highlightbackground="#30445f", highlightthickness=1)
        sport_box.pack(fill="x", padx=16, pady=(0, 7))
        sport_head = tk.Frame(sport_box, bg=PANEL)
        sport_head.pack(fill="x", padx=12, pady=(9, 3))
        tk.Label(sport_head, text="🏆  MEILLEURS SPORTS", bg=PANEL, fg=TEXT, font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Label(sport_head, text="Performance réelle", bg=PANEL, fg=MUTED, font=("Segoe UI", 8)).pack(side="right")
        self.sports_rows = tk.Frame(sport_box, bg=PANEL)
        self.sports_rows.pack(fill="x", padx=12, pady=(0, 9))
        self._render_sports([])

        status_box = tk.Frame(self, bg="#101d30")
        status_box.pack(fill="x", padx=16, pady=(0, 8))
        self.status = tk.Label(status_box, bg="#101d30", fg=MUTED, font=("Segoe UI", 8), justify="left", anchor="w", wraplength=438)
        self.status.pack(fill="x", padx=11, pady=8)

        actions = tk.Frame(self, bg=BG)
        actions.pack(fill="x", padx=16, pady=(0, 14))
        self._action(actions, "G   Connexion Google sécurisée", self.open_google_login, ACCENT, "#ffffff", fill=True).pack(fill="x")
        secondary = tk.Frame(actions, bg=BG)
        secondary.pack(fill="x", pady=(7, 0))
        self._action(secondary, "Code", self.connect_with_code, PANEL_ALT, TEXT).pack(side="left", expand=True, fill="x")
        self._action(secondary, "Bureau", self.create_desktop_shortcut, PANEL_ALT, TEXT).pack(side="left", expand=True, fill="x", padx=6)
        self._action(secondary, "Actualiser", self.refresh, PANEL_ALT, TEXT).pack(side="left", expand=True, fill="x", padx=(0, 6))
        self._action(secondary, "Site", self.open_site, PANEL_ALT, TEXT).pack(side="left", expand=True, fill="x")

    def _metric(self, parent: tk.Frame, label: str, value: str, row: int, column: int, accent: str, key: str, icon: str) -> tk.Label:
        parent.grid_columnconfigure(column, weight=1)
        parent.grid_rowconfigure(row, weight=1)
        card = tk.Frame(parent, bg=PANEL, highlightbackground=accent, highlightthickness=1, height=82)
        card.grid(row=row, column=column, padx=(0, 5) if column == 0 else (5, 0), pady=5, sticky="nsew")
        card.grid_propagate(False)
        marker = tk.Frame(card, bg=accent, height=2)
        marker.pack(fill="x")
        body = tk.Frame(card, bg=PANEL)
        body.pack(fill="both", expand=True, padx=10, pady=(5, 6))
        tk.Label(body, text=icon, bg="#182943", fg=accent, font=("Segoe UI Symbol", 14, "bold"), width=2).pack(side="left", anchor="n", padx=(0, 8))
        copy = tk.Frame(body, bg=PANEL)
        copy.pack(side="left", fill="both", expand=True)
        tk.Label(copy, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")
        shown = tk.Label(copy, text=value, bg=PANEL, fg=TEXT, font=("Segoe UI", 15, "bold"))
        shown.pack(anchor="w", pady=(1, 0))
        detail = tk.Label(copy, text="En attente de données", bg=PANEL, fg=MUTED, font=("Segoe UI", 7))
        detail.pack(anchor="w")
        self.metric_details[key] = detail
        return shown

    def _render_sports(self, sports: list[tuple[str, float]]) -> None:
        """Affiche uniquement les meilleurs sports présents dans les données du compte."""
        for child in self.sports_rows.winfo_children():
            child.destroy()

        top_sports = sports[:3]
        if not top_sports:
            tk.Label(
                self.sports_rows,
                text="Aucun pari réglé pour cette période.",
                bg=PANEL,
                fg=MUTED,
                font=("Segoe UI", 8),
                anchor="w",
            ).pack(fill="x", pady=(3, 5))
            return

        maximum = max(1.0, *(abs(profit) for _, profit in top_sports))
        for index, (sport, profit) in enumerate(top_sports):
            row = tk.Frame(self.sports_rows, bg=PANEL)
            row.pack(fill="x", pady=(2 if index else 0, 5))

            title = tk.Label(row, text=sport, bg=PANEL, fg=TEXT, font=("Segoe UI", 8, "bold"), anchor="w")
            title.pack(side="left")
            amount = tk.Label(
                row,
                text=eur(profit),
                bg=PANEL,
                fg=GOOD if profit >= 0 else BAD,
                font=("Segoe UI", 8, "bold"),
                anchor="e",
            )
            amount.pack(side="right")

            bar = tk.Canvas(self.sports_rows, height=5, bg=PANEL, highlightthickness=0, bd=0)
            bar.pack(fill="x", pady=(0, 2))
            bar.update_idletasks()
            width = max(bar.winfo_width(), 280)
            bar.create_rectangle(0, 0, width, 5, fill="#20344d", outline="")
            fill_width = max(7, int(width * abs(profit) / maximum))
            bar.create_rectangle(0, 0, fill_width, 5, fill=GOOD if profit >= 0 else BAD, outline="")

    def _redraw_sparkline(self, _event=None) -> None:
        canvas = self.sparkline
        canvas.delete("all")
        width = max(canvas.winfo_width(), 360)
        height = max(canvas.winfo_height(), 132)
        left, right, top, bottom = 14, width - 14, 12, height - 18

        for fraction in (0.2, 0.4, 0.6, 0.8):
            y = top + (bottom - top) * fraction
            canvas.create_line(left, y, right, y, fill="#263b55", dash=(2, 4))

        if len(self._sparkline_values) < 2:
            canvas.create_text(
                width / 2,
                height / 2,
                text="Les prochains paris feront apparaître ta courbe",
                fill=MUTED,
                font=("Segoe UI", 8),
            )
            return

        progress = 1 - (1 - self._sparkline_progress) ** 3
        count = max(2, min(len(self._sparkline_values), round((len(self._sparkline_values) - 1) * progress) + 1))
        values = self._sparkline_values[:count]
        low, high = min(self._sparkline_values), max(self._sparkline_values)
        margin = max((high - low) * 0.14, 1)
        low -= margin
        high += margin
        span = high - low or 1
        step = (right - left) / max(len(self._sparkline_values) - 1, 1)
        points = [
            (left + index * step, bottom - (value - low) / span * (bottom - top))
            for index, value in enumerate(values)
        ]
        flat = [coordinate for point in points for coordinate in point]
        color = ACCENT if self._sparkline_values[-1] >= self._sparkline_values[0] else BAD
        area = [left, bottom, *flat, points[-1][0], bottom]
        canvas.create_polygon(area, fill="#372a25" if color == ACCENT else "#422432", outline="")
        canvas.create_line(*flat, fill="#68432e" if color == ACCENT else "#5e3040", width=7, smooth=True, splinesteps=20)
        canvas.create_line(*flat, fill=color, width=3, smooth=True, splinesteps=20)
        x, y = points[-1]
        canvas.create_oval(x - 5, y - 5, x + 5, y + 5, fill=color, outline=PANEL, width=2)

    def _animate_sparkline(self, values: list[float]) -> None:
        if self._sparkline_job:
            self.after_cancel(self._sparkline_job)
        self._sparkline_values = values
        self._sparkline_progress = 0.0

        def tick() -> None:
            self._sparkline_progress = min(1.0, self._sparkline_progress + 0.09)
            self._redraw_sparkline()
            if self._sparkline_progress < 1:
                self._sparkline_job = self.after(16, tick)
            else:
                self._sparkline_job = None

        tick()

    @staticmethod
    def _action(parent: tk.Frame, text: str, command, background: str, foreground: str, fill: bool = False) -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=background, fg=foreground, activebackground=ACCENT_DARK if background == ACCENT else background, activeforeground=foreground, relief="flat", bd=0, padx=12 if fill else 10, pady=8 if fill else 7, font=("Segoe UI", 9, "bold"), cursor="hand2")

    def _start_drag(self, event) -> None:
        self._drag_origin = (event.x, event.y)

    def _drag(self, event) -> None:
        if self._drag_origin:
            x = self.winfo_x() + event.x - self._drag_origin[0]
            y = self.winfo_y() + event.y - self._drag_origin[1]
            self.geometry(f"+{x}+{y}")

    def _load_brand_image(self) -> None:
        """Affiche le renard fourni, localement ou après un téléchargement discret."""
        image_found = False
        for path in (BUNDLED_BRAND_IMAGE_PATH, BRAND_IMAGE_PATH):
            if path.is_file():
                self._apply_brand_image(path)
                image_found = True
                break
        if not image_found:
            threading.Thread(target=self._download_brand_image, daemon=True).start()
        self._set_window_icon()
        if not self._brand_icon_path():
            threading.Thread(target=self._download_brand_icon, daemon=True).start()

    @staticmethod
    def _brand_icon_path() -> Path | None:
        for path in (BUNDLED_BRAND_ICON_PATH, BRAND_ICON_PATH):
            if path.is_file():
                return path
        return None

    def _set_window_icon(self) -> None:
        icon_path = self._brand_icon_path()
        if not icon_path:
            return
        try:
            self.iconbitmap(default=str(icon_path))
        except tk.TclError:
            pass

    def _download_brand_image(self) -> None:
        """Met en cache le visuel public pour garder le widget autonome ensuite."""
        try:
            base_url = (self.base_url or DEFAULT_SITE_URL).rstrip("/")
            request = urllib.request.Request(
                base_url + BRAND_IMAGE_URL,
                headers={"User-Agent": "BET.PRONO-Widget/2.5"},
            )
            with urllib.request.urlopen(request, timeout=6) as response:
                image_data = response.read(3_000_000)
            if not image_data.startswith(b"\x89PNG\r\n\x1a\n"):
                return
            BRAND_IMAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = BRAND_IMAGE_PATH.with_suffix(".tmp")
            temporary_path.write_bytes(image_data)
            temporary_path.replace(BRAND_IMAGE_PATH)
        except (OSError, urllib.error.URLError):
            return
        self.after(0, lambda: self._apply_brand_image(BRAND_IMAGE_PATH))

    def _download_brand_icon(self) -> None:
        """Met l'icône Windows en cache pour le raccourci Bureau et la barre des tâches."""
        try:
            base_url = (self.base_url or DEFAULT_SITE_URL).rstrip("/")
            request = urllib.request.Request(
                base_url + BRAND_ICON_URL,
                headers={"User-Agent": "BET.PRONO-Widget/2.5"},
            )
            with urllib.request.urlopen(request, timeout=6) as response:
                icon_data = response.read(1_000_000)
            if not icon_data.startswith(b"\x00\x00\x01\x00"):
                return
            BRAND_ICON_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = BRAND_ICON_PATH.with_suffix(".tmp")
            temporary_path.write_bytes(icon_data)
            temporary_path.replace(BRAND_ICON_PATH)
        except (OSError, urllib.error.URLError):
            return
        self.after(0, self._set_window_icon)

    def _apply_brand_image(self, path: Path) -> None:
        try:
            full_size = tk.PhotoImage(file=str(path))
            scale = max(1, max(full_size.width(), full_size.height()) // 48)
            thumbnail = full_size.subsample(scale, scale)
        except tk.TclError:
            return
        self._brand_image_full = full_size
        self._brand_image = thumbnail
        self.brand_mark.configure(image=thumbnail, text="", width=0)
        self.iconphoto(True, full_size)

    def _load_url(self) -> str:
        try:
            return str(json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("base_url", ""))
        except (OSError, json.JSONDecodeError):
            return ""

    def _save_url(self) -> None:
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps({"base_url": self.base_url}), encoding="utf-8")
        except OSError:
            pass

    def _set_period(self, days: int | None) -> None:
        self.period_days = days
        self._paint_periods()
        if self.client:
            self.refresh()

    def _paint_periods(self) -> None:
        for days, button in self.period_buttons.items():
            active = days == self.period_days
            button.configure(bg=ACCENT if active else PANEL, fg="#ffffff" if active else MUTED, activebackground=ACCENT if active else PANEL, activeforeground="#ffffff" if active else MUTED)

    def _set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def _ask_site_address(self, message: str) -> str | None:
        """Demande et mémorise seulement l'adresse du site, jamais un mot de passe."""
        address = simpledialog.askstring(
            APP_NAME,
            message,
            initialvalue=self.base_url or "https://",
            parent=self,
        )
        if not address or address == "https://":
            return None
        if "://" not in address:
            address = "https://" + address
        parsed = urllib.parse.urlparse(address)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            messagebox.showerror(APP_NAME, "Cette adresse ne semble pas valide.", parent=self)
            return None
        self.base_url = address.rstrip("/")
        self._save_url()
        return self.base_url

    def _set_connected_badge(self, connected: bool) -> None:
        if connected:
            self.connection_badge.configure(text="● CONNECTÉ", bg="#123529", fg=GOOD)
        else:
            self.connection_badge.configure(text="● HORS LIGNE", bg="#172235", fg=MUTED)

    def open_google_login(self) -> None:
        address = self._ask_site_address(
            "Adresse publique de BET.PRONO :\n\nLa connexion Google se fera en sécurité dans ton navigateur."
        )
        if not address:
            return
        webbrowser.open(address + "/app")
        self._set_status("Dans le site : Profil → Widget bureau → Générer un code, puis reviens ici avec ce code.")

    def connect_with_code(self) -> None:
        address = self._ask_site_address("Adresse publique de BET.PRONO :")
        if not address:
            return
        code = simpledialog.askstring(
            APP_NAME,
            "Colle le code créé dans BET.PRONO :\nProfil → Widget bureau → Générer un code",
            parent=self,
        )
        if not code:
            return
        try:
            client = BetPronoApi(address)
            client.pair(code)
            self.client = client
            self._set_connected_badge(True)
            self._set_status("Widget connecté de façon sécurisée. Actualisation des statistiques…")
            self.refresh()
        except RuntimeError as error:
            self._set_connected_badge(False)
            messagebox.showerror(APP_NAME, error, parent=self)

    def refresh(self) -> None:
        if not self.client:
            self._set_status("Connecte-toi via Google, puis choisis « Entrer le code » pour afficher tes statistiques.")
            messagebox.showinfo(APP_NAME, "Utilise « Connexion Google », puis « Entrer le code » pour lier le widget sans mot de passe.", parent=self)
            return
        try:
            data = self.client.bets()
            metrics = compute_metrics(data.get("bets", []), data.get("initial_bankroll", 0), self.period_days)
            self.bankroll.configure(text=eur(metrics["bankroll"]), fg=GOOD if metrics["bankroll"] >= 0 else BAD)
            self.profit.configure(text=eur(metrics["profit"]), fg=GOOD if metrics["profit"] >= 0 else BAD)
            self.roi.configure(text=percent(metrics["roi"]), fg=GOOD if (metrics["roi"] or 0) > 0 else BAD if (metrics["roi"] or 0) < 0 else TEXT)
            self.win_rate.configure(text=percent(metrics["win_rate"]), fg=TEXT)
            self.metric_details["bankroll"].configure(text=f"Initiale : {eur(data.get('initial_bankroll', 0))}")
            self.metric_details["profit"].configure(text=f"{metrics['settled']} pari(s) réglé(s)")
            self.metric_details["roi"].configure(text="Bénéfice net / mises")
            decisive = metrics["decisive"]
            self.metric_details["win_rate"].configure(text=f"{metrics['wins']} gagnés / {decisive}" if decisive else "Aucun pari décisif")
            self.chart_value.configure(text=eur(metrics["curve"][-1]) if metrics["curve"] else "—")
            label = "tout l’historique" if self.period_days is None else f"les {self.period_days} derniers jours"
            self.chart_caption.configure(text=f"Bankroll sur {label} • animation à chaque actualisation")
            self._animate_sparkline(metrics["curve"])
            self._render_sports(metrics["sports"])
            self.summary.configure(
                text=f"✓ {metrics['wins']} gagnés   ✕ {metrics['losses']} perdus   • {metrics['pending']} en attente"
            )
            self._set_status(f"{metrics['settled']} pari(s) réglé(s), {metrics['pending']} en attente — {label}.\nMis à jour à {dt.datetime.now().strftime('%H:%M')}")
        except RuntimeError as error:
            self._set_connected_badge(False)
            self._set_status("Session expirée : reconnecte-toi pour actualiser les chiffres.")
            messagebox.showwarning(APP_NAME, str(error), parent=self)

    def open_site(self) -> None:
        address = self.base_url or self._ask_site_address("Adresse publique de BET.PRONO :")
        if not address:
            return
        webbrowser.open(address + ("/app" if self.client else "/login"))

    def create_desktop_shortcut(self) -> None:
        """Installe un raccourci Bureau stable, avec l'icône renard au lieu de Python."""
        icon_path = self._brand_icon_path()
        if not icon_path:
            threading.Thread(target=self._download_brand_icon, daemon=True).start()
            messagebox.showinfo(
                APP_NAME,
                "Le logo est en cours de préparation. Attends quelques secondes puis clique à nouveau sur « Bureau ».",
                parent=self,
            )
            return

        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            installed_script = CONFIG_PATH.parent / Path(__file__).name
            if Path(__file__).resolve() != installed_script.resolve():
                shutil.copy2(Path(__file__).resolve(), installed_script)
            installed_icon = CONFIG_PATH.parent / BRAND_ICON_NAME
            if icon_path.resolve() != installed_icon.resolve():
                shutil.copy2(icon_path, installed_icon)

            python_executable = Path(sys.executable)
            pythonw = python_executable.with_name("pythonw.exe")
            if pythonw.is_file():
                python_executable = pythonw

            def power_shell_literal(value: Path) -> str:
                return "'" + str(value).replace("'", "''") + "'"

            command = (
                "$shell = New-Object -ComObject WScript.Shell; "
                "$shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'BET.PRONO Widget.lnk')); "
                f"$shortcut.TargetPath = {power_shell_literal(python_executable)}; "
                f"$shortcut.Arguments = {power_shell_literal(installed_script)}; "
                f"$shortcut.WorkingDirectory = {power_shell_literal(CONFIG_PATH.parent)}; "
                f"$shortcut.IconLocation = {power_shell_literal(installed_icon)} + ',0'; "
                "$shortcut.Description = 'BET.PRONO — tableau de bord bureau'; $shortcut.Save()"
            )
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as error:
            messagebox.showerror(APP_NAME, f"Impossible de créer le raccourci Bureau.\n\n{error}", parent=self)
            return

        self._set_status("Raccourci Bureau créé avec le logo renard. Tu peux désormais lancer le widget depuis cette icône.")
        messagebox.showinfo(APP_NAME, "Le raccourci BET.PRONO avec le logo renard est prêt sur ton Bureau.", parent=self)


if __name__ == "__main__":
    BetPronoWidget().mainloop()


