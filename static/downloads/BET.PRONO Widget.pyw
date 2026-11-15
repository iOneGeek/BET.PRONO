"""BET.PRONO Widget — ouvre BET.PRONO dans sa propre fenêtre d'application Edge.

Comme le panneau « Œil du Trader » : une vraie fenêtre Windows (agrandir, plein écran,
redimensionner à la main), sans barre d'adresse, avec un profil Edge réservé au widget.
Tu te connectes une fois (Google ou identifiant) et tu restes connecté d'un lancement à l'autre.

Ce fichier n'utilise que la bibliothèque standard de Python et ne stocke aucun mot de passe :
la session est gardée par Edge dans le profil du widget, comme dans un navigateur.
Lancement : double-clic sur ce fichier ou sur le raccourci « BET.PRONO Widget » du Bureau.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "BET.PRONO Widget"
WIDGET_VERSION = "V3.0.0"
DEFAULT_SITE_URL = "https://bet-prono.onrender.com"
HOME = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
CONFIG_PATH = HOME / "config.json"
# Profil Edge propre au widget (session, taille de fenêtre) : séparé de ton navigateur habituel.
PROFILE_DIR = Path(os.environ.get("LOCALAPPDATA", str(HOME))) / APP_NAME / "fenetre"
ICON_NAME = "bet-prono-widget-logo.ico"
INSTALLED_SCRIPT = HOME / "BET.PRONO Widget.pyw"
INSTALLED_ICON = HOME / ICON_NAME
FIRST_WINDOW_SIZE = "520,960"

MB_OK, MB_ICONINFO, MB_ICONERROR, MB_TOPMOST = 0x0, 0x40, 0x10, 0x40000


def message(text: str, error: bool = False) -> None:
    """Petite boîte de dialogue Windows (le widget n'a pas de console)."""
    try:
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, MB_OK | MB_TOPMOST | (MB_ICONERROR if error else MB_ICONINFO))
    except (AttributeError, OSError):
        print(text)


def site_url() -> str:
    """Adresse du site : celle mémorisée par les versions précédentes, sinon l'adresse officielle."""
    try:
        value = str(json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("base_url", "")).strip()
    except (OSError, json.JSONDecodeError):
        value = ""
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        return value.rstrip("/")
    return DEFAULT_SITE_URL


def find_edge() -> Path | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base:
            path = Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if path.exists():
                return path
    return None


def open_window(url: str) -> bool:
    """Ouvre la fenêtre d'application. Retourne False si Edge est introuvable (navigateur par défaut)."""
    edge = find_edge()
    if edge is None:
        webbrowser.open(url)
        return False
    first_launch = not PROFILE_DIR.exists()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    arguments = [
        str(edge), f"--app={url}", f"--user-data-dir={PROFILE_DIR}",
        "--no-first-run", "--no-default-browser-check", "--disable-sync",
        "--disable-features=Translate,msEdgeSidebarV2",
    ]
    if first_launch:
        # Ensuite, Edge se souvient de la taille et de la position que tu as choisies.
        arguments.append(f"--window-size={FIRST_WINDOW_SIZE}")
    subprocess.Popen(arguments, close_fds=True)
    return True


def fetch_icon(base_url: str) -> Path | None:
    """Icône renard du raccourci : à côté du script, déjà installée, ou téléchargée depuis le site."""
    for path in (Path(__file__).with_name(ICON_NAME), INSTALLED_ICON):
        if path.is_file():
            return path
    try:
        request = urllib.request.Request(f"{base_url}/static/downloads/{ICON_NAME}", headers={"User-Agent": "BET.PRONO-Widget/3.0"})
        with urllib.request.urlopen(request, timeout=20) as response:
            data = response.read(1_000_000)
        if not data.startswith(b"\x00\x00\x01\x00"):
            return None
        HOME.mkdir(parents=True, exist_ok=True)
        INSTALLED_ICON.write_bytes(data)
        return INSTALLED_ICON
    except (OSError, urllib.error.URLError, TimeoutError):
        return None


def install_shortcut(base_url: str) -> None:
    """Copie le widget dans AppData et (re)crée le raccourci Bureau avec le logo renard.

    Sans effet si tout est déjà en place. Une erreur ici n'empêche jamais d'ouvrir la fenêtre.
    """
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        here = Path(__file__).resolve()
        if here != INSTALLED_SCRIPT.resolve():
            shutil.copy2(here, INSTALLED_SCRIPT)
        icon = fetch_icon(base_url)
        if icon and icon.resolve() != INSTALLED_ICON.resolve():
            shutil.copy2(icon, INSTALLED_ICON)
        python = Path(sys.executable)
        if python.with_name("pythonw.exe").is_file():
            python = python.with_name("pythonw.exe")

        def literal(value: Path) -> str:
            return "'" + str(value).replace("'", "''") + "'"
        command = (
            "$shell = New-Object -ComObject WScript.Shell; "
            "$path = Join-Path ([Environment]::GetFolderPath('Desktop')) 'BET.PRONO Widget.lnk'; "
            "$shortcut = $shell.CreateShortcut($path); "
            f"$shortcut.TargetPath = {literal(python)}; "
            f"$shortcut.Arguments = '\"' + {literal(INSTALLED_SCRIPT)} + '\"'; "
            f"$shortcut.WorkingDirectory = {literal(HOME)}; "
            + (f"$shortcut.IconLocation = {literal(INSTALLED_ICON)} + ',0'; " if INSTALLED_ICON.is_file() else "")
            + "$shortcut.Description = 'BET.PRONO — fenêtre d''application'; $shortcut.Save()"
        )
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                       check=True, capture_output=True, text=True, timeout=15,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        pass


def main() -> None:
    base_url = site_url()
    try:
        opened = open_window(base_url + "/app")
    except OSError as error:
        message(f"Impossible d’ouvrir la fenêtre BET.PRONO.\n\n{error}", error=True)
        return
    # Après l'ouverture, pour ne pas la retarder. Répare aussi les anciens raccourcis
    # dont le chemin avec espaces n'était pas entre guillemets (le clic ne faisait rien).
    install_shortcut(base_url)
    if not opened:
        message("Microsoft Edge est introuvable : BET.PRONO s’ouvre dans ton navigateur habituel.\n\n"
                "Installe Edge pour retrouver la fenêtre d’application agrandissable.")


if __name__ == "__main__":
    main()
