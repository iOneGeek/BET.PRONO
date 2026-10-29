"""Widget Windows autonome pour consulter BET.PRONO depuis le bureau.

Ce fichier n'utilise que la bibliothèque standard de Python. Il ne conserve jamais
le mot de passe : la session API reste uniquement en mémoire pendant l'exécution.
"""

from __future__ import annotations

import datetime as dt
import json
import os
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
CONFIG_PATH = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME / "config.json"
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
        self.geometry("410x656+48+96")
        self.client: BetPronoApi | None = None
        self.base_url = self._load_url()
        self.period_days: int | None = 30
        self.period_buttons: dict[int | None, tk.Button] = {}
        self._drag_origin: tuple[int, int] | None = None
        self._sparkline_values: list[float] = []
        self._sparkline_progress = 1.0
        self._sparkline_job: str | None = None

        self._build()
        self._set_status("Connecte ton compte pour afficher tes statistiques.")

    def _build(self) -> None:
        header = tk.Frame(self, bg=HEADER, height=70)
        header.pack(fill="x")
        header.pack_propagate(False)
        for widget in (header,):
            widget.bind("<ButtonPress-1>", self._start_drag)
            widget.bind("<B1-Motion>", self._drag)

        accent = tk.Frame(header, bg=ACCENT, width=5)
        accent.pack(side="left", fill="y")
        brand = tk.Frame(header, bg=HEADER)
        brand.pack(side="left", fill="both", expand=True, padx=(13, 0), pady=11)
        tk.Label(brand, text="BET.PRONO", bg=HEADER, fg=TEXT, font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(brand, text="TON TABLEAU DE BORD • BUREAU", bg=HEADER, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(1, 0))
        self.connection_badge = tk.Label(header, text="● HORS LIGNE", bg="#172235", fg=MUTED, font=("Segoe UI", 8, "bold"), padx=8, pady=4)
        self.connection_badge.pack(side="right", padx=(0, 4), pady=20)
        close = tk.Button(header, text="×", command=self.destroy, bg=HEADER, fg=MUTED, bd=0, font=("Segoe UI", 17), activebackground=HEADER, activeforeground=TEXT)
        close.pack(side="right", padx=7)

        periods = tk.Frame(self, bg=BG)
        periods.pack(fill="x", padx=14, pady=(15, 6))
        tk.Label(periods, text="PÉRIODE", bg=BG, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 10))
        for label, days in (("7 j", 7), ("30 j", 30), ("90 j", 90), ("Tout", None)):
            button = tk.Button(periods, text=label, command=lambda value=days: self._set_period(value), relief="flat", bd=0, padx=10, pady=5, font=("Segoe UI", 9, "bold"), cursor="hand2")
            button.pack(side="left", padx=(0, 5))
            self.period_buttons[days] = button
        self._paint_periods()

        cards = tk.Frame(self, bg=BG)
        cards.pack(fill="x", padx=14)
        self.bankroll = self._metric(cards, "BANKROLL", "—", 0, 0, "#38bdf8")
        self.profit = self._metric(cards, "BÉNÉFICE", "—", 0, 1, GOOD)
        self.roi = self._metric(cards, "ROI", "—", 1, 0, ACCENT)
        self.win_rate = self._metric(cards, "RÉUSSITE", "—", 1, 1, "#a78bfa")

        chart_box = tk.Frame(self, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        chart_box.pack(fill="x", padx=14, pady=(7, 7))
        chart_head = tk.Frame(chart_box, bg=PANEL)
        chart_head.pack(fill="x", padx=12, pady=(9, 0))
        tk.Label(chart_head, text="ÉVOLUTION", bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(side="left")
        self.chart_value = tk.Label(chart_head, text="—", bg=PANEL, fg="#38bdf8", font=("Segoe UI", 10, "bold"))
        self.chart_value.pack(side="right")
        self.sparkline = tk.Canvas(chart_box, height=92, bg=PANEL, highlightthickness=0, bd=0)
        self.sparkline.pack(fill="x", padx=6, pady=(2, 0))
        self.sparkline.bind("<Configure>", self._redraw_sparkline)
        self.chart_caption = tk.Label(chart_box, text="Connecte ton compte pour voir ta courbe.", bg=PANEL, fg=MUTED, font=("Segoe UI", 8), anchor="w")
        self.chart_caption.pack(fill="x", padx=12, pady=(0, 9))

        sport_box = tk.Frame(self, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        sport_box.pack(fill="x", padx=14, pady=(0, 7))
        tk.Label(sport_box, text="MEILLEURS SPORTS", bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=12, pady=(10, 3))
        self.sports = tk.Label(sport_box, text="Aucune donnée réglée pour cette période.", bg=PANEL, fg=TEXT, font=("Segoe UI", 9), justify="left", anchor="w", wraplength=348)
        self.sports.pack(fill="x", padx=12, pady=(0, 10))

        self.status = tk.Label(self, bg=BG, fg=MUTED, font=("Segoe UI", 8), justify="left", anchor="w", wraplength=376)
        self.status.pack(fill="x", padx=16, pady=(4, 9))

        actions = tk.Frame(self, bg=BG)
        actions.pack(fill="x", padx=14, pady=(0, 13))
        self._action(actions, "G  Connexion Google", self.open_google_login, ACCENT, "#ffffff", fill=True).pack(fill="x")
        secondary = tk.Frame(actions, bg=BG)
        secondary.pack(fill="x", pady=(7, 0))
        self._action(secondary, "Entrer le code", self.connect_with_code, PANEL_ALT, TEXT).pack(side="left")
        self._action(secondary, "Actualiser", self.refresh, PANEL_ALT, TEXT).pack(side="left", padx=7)
        self._action(secondary, "Ouvrir le site", self.open_site, PANEL_ALT, TEXT).pack(side="right")

    def _metric(self, parent: tk.Frame, label: str, value: str, row: int, column: int, accent: str) -> tk.Label:
        parent.grid_columnconfigure(column, weight=1)
        card = tk.Frame(parent, bg=PANEL, highlightbackground=LINE, highlightthickness=1)
        card.grid(row=row, column=column, padx=(0, 6) if column == 0 else (6, 0), pady=6, sticky="nsew")
        marker = tk.Frame(card, bg=accent, height=3)
        marker.pack(fill="x")
        tk.Label(card, text=label, bg=PANEL, fg=MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=12, pady=(8, 0))
        shown = tk.Label(card, text=value, bg=PANEL, fg=TEXT, font=("Segoe UI", 17, "bold"))
        shown.pack(anchor="w", padx=12, pady=(1, 10))
        return shown

    def _redraw_sparkline(self, _event=None) -> None:
        canvas = self.sparkline
        canvas.delete("all")
        width = max(canvas.winfo_width(), 360)
        height = max(canvas.winfo_height(), 92)
        left, right, top, bottom = 10, width - 10, 10, height - 12

        for fraction in (0.25, 0.5, 0.75):
            y = top + (bottom - top) * fraction
            canvas.create_line(left, y, right, y, fill="#2c3c55", dash=(2, 4))

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
        color = GOOD if self._sparkline_values[-1] >= self._sparkline_values[0] else BAD
        area = [left, bottom, *flat, points[-1][0], bottom]
        canvas.create_polygon(area, fill="#173f48" if color == GOOD else "#492635", outline="")
        canvas.create_line(*flat, fill=color, width=3, smooth=True, splinesteps=20)
        x, y = points[-1]
        canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=color, outline=PANEL, width=2)

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
            self.chart_value.configure(text=eur(metrics["curve"][-1]) if metrics["curve"] else "—")
            label = "tout l’historique" if self.period_days is None else f"les {self.period_days} derniers jours"
            self.chart_caption.configure(text=f"Bankroll sur {label} • animation à chaque actualisation")
            self._animate_sparkline(metrics["curve"])
            if metrics["sports"]:
                self.sports.configure(text="  •  ".join(f"{sport} {eur(value)}" for sport, value in metrics["sports"][:3]))
            else:
                self.sports.configure(text="Aucun pari réglé pour cette période.")
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


if __name__ == "__main__":
    BetPronoWidget().mainloop()
