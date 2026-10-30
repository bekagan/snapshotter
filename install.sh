#!/usr/bin/env bash
# Installs Snapshotter for the current user (no sudo required).
# Re-running this script updates an existing installation, including yt-dlp.
set -euo pipefail

APP_ID="snapshotter"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA_HOME/$APP_ID"
VENV_DIR="$APP_DIR/venv"
BIN_DIR="$HOME/.local/bin"
LAUNCHER="$BIN_DIR/$APP_ID"
DESKTOP_DIR="$DATA_HOME/applications"
DESKTOP_FILE="$DESKTOP_DIR/$APP_ID.desktop"
ICON_ROOT="$DATA_HOME/icons/hicolor"
MIN_PYTHON="3.9"

if [ -t 1 ]; then
    BOLD=$'\e[1m'; RED=$'\e[31m'; GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RESET=$'\e[0m'
else
    BOLD=""; RED=""; GREEN=""; YELLOW=""; RESET=""
fi
step() { printf '%s==>%s %s\n' "$BOLD" "$RESET" "$*"; }
ok()   { printf '    %s✓%s %s\n' "$GREEN" "$RESET" "$*"; }
warn() { printf '    %s!%s %s\n' "$YELLOW" "$RESET" "$*"; }
die()  { printf '%sError:%s %s\n' "$RED" "$RESET" "$*" >&2; exit 1; }

if [ "$(id -u)" -eq 0 ]; then
    die "Run install.sh as your normal user, not root. It installs into your home directory."
fi

for required in main.py requirements.txt app/window.py assets/icon.svg assets/icon.png linux/snapshotter.desktop; do
    [ -f "$SRC_DIR/$required" ] || die "Missing $required. Run install.sh from the Snapshotter project folder."
done

# Prints the package-manager command that installs the given packages, if known.
install_command() {
    if command -v apt-get >/dev/null 2>&1; then echo "sudo apt-get install -y $*"
    elif command -v dnf >/dev/null 2>&1; then echo "sudo dnf install -y $*"
    elif command -v pacman >/dev/null 2>&1; then echo "sudo pacman -S --needed --noconfirm $*"
    elif command -v zypper >/dev/null 2>&1; then echo "sudo zypper install -y $*"
    fi
}

# --- 1. Python -----------------------------------------------------------
step "Checking Python"
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 &&
       "$candidate" -c "import sys; sys.exit(sys.version_info < (${MIN_PYTHON/./, }))" 2>/dev/null; then
        PYTHON="$(command -v "$candidate")"
        break
    fi
done
[ -n "$PYTHON" ] || die "Python $MIN_PYTHON or newer is required. Install it with: $(install_command python3 || echo 'your package manager')"
PY_VERSION="$("$PYTHON" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
ok "Python $PY_VERSION ($PYTHON)"

if ! "$PYTHON" -c "import venv, ensurepip" >/dev/null 2>&1; then
    hint="$(install_command "python${PY_VERSION}-venv" || true)"
    die "Python's venv module is not available.${hint:+ Install it with:
    $hint}"
fi

# --- 2. FFmpeg -----------------------------------------------------------
step "Checking FFmpeg"
if command -v ffmpeg >/dev/null 2>&1; then
    ok "$(ffmpeg -version 2>/dev/null | head -n1 | cut -d' ' -f1-3)"
else
    warn "FFmpeg is not installed. It is needed to merge separate video and audio"
    warn "streams; without it Snapshotter can only download lower-quality files."
    cmd="$(install_command ffmpeg || true)"
    if [ -n "$cmd" ] && [ -t 0 ]; then
        read -r -p "    Install FFmpeg now with '$cmd'? [y/N] " reply
        if [[ "$reply" =~ ^[Yy]$ ]]; then
            if $cmd; then ok "FFmpeg installed"; else warn "FFmpeg installation failed; continuing without it."; fi
        else
            warn "Skipped. Install it later with: $cmd"
        fi
    elif [ -n "$cmd" ]; then
        warn "Install it with: $cmd"
    else
        warn "Install the 'ffmpeg' package with your distribution's package manager."
    fi
fi

# --- 3. Optional runtime helpers ----------------------------------------
step "Checking optional components"
if command -v deno >/dev/null 2>&1 || [ -x "$HOME/.deno/bin/deno" ]; then
    ok "JavaScript runtime: deno"
elif command -v node >/dev/null 2>&1; then
    ok "JavaScript runtime: node ($(node --version 2>/dev/null))"
elif command -v bun >/dev/null 2>&1 || [ -x "$HOME/.bun/bin/bun" ]; then
    ok "JavaScript runtime: bun"
else
    warn "No JavaScript runtime found. yt-dlp needs one (deno recommended, or Node.js)"
    warn "to access every YouTube format. See https://docs.deno.com/runtime/getting_started/installation/"
fi
if [ "${XDG_SESSION_TYPE:-}" = "x11" ] && command -v ldconfig >/dev/null 2>&1 &&
   ! ldconfig -p 2>/dev/null | grep -q 'libxcb-cursor\.so\.0'; then
    warn "Qt needs libxcb-cursor on X11 sessions. Install it with: $(install_command libxcb-cursor0 || echo 'your package manager')"
else
    ok "Display libraries"
fi

# --- 4. Application files -------------------------------------------------
step "Installing application files to $APP_DIR"
mkdir -p "$APP_DIR"
rm -rf "$APP_DIR/app" "$APP_DIR/assets" "$APP_DIR/main.py"
cp -r "$SRC_DIR/app" "$SRC_DIR/assets" "$APP_DIR/"
cp "$SRC_DIR/main.py" "$SRC_DIR/requirements.txt" "$APP_DIR/"
cp "$SRC_DIR/uninstall.sh" "$APP_DIR/uninstall.sh"
chmod +x "$APP_DIR/uninstall.sh"
find "$APP_DIR/app" -name '__pycache__' -type d -prune -exec rm -rf {} +
ok "Copied application files"

# --- 5. Virtual environment ------------------------------------------------
step "Setting up the Python virtual environment"
if [ -x "$VENV_DIR/bin/python" ] &&
   [ "$("$VENV_DIR/bin/python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" = "$PY_VERSION" ]; then
    ok "Reusing existing environment"
else
    rm -rf "$VENV_DIR"
    "$PYTHON" -m venv "$VENV_DIR" || die "Could not create the virtual environment."
    ok "Created $VENV_DIR"
fi

step "Installing dependencies (this can take a minute)"
"$VENV_DIR/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip ||
    warn "Could not upgrade pip; continuing with the bundled version."
"$VENV_DIR/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade -r "$APP_DIR/requirements.txt" ||
    die "Dependency installation failed. Check your internet connection and run install.sh again."
"$VENV_DIR/bin/python" -c "import PySide6.QtWidgets, PySide6.QtSvg, yt_dlp" ||
    die "Dependencies were installed but cannot be imported."
"$VENV_DIR/bin/python" -m compileall -q "$APP_DIR/app" "$APP_DIR/main.py" >/dev/null || true
ok "PySide6 $("$VENV_DIR/bin/python" -c 'import PySide6; print(PySide6.__version__)'), yt-dlp $("$VENV_DIR/bin/python" -c 'from yt_dlp.version import __version__; print(__version__)')"

# --- 6. Launcher ---------------------------------------------------------------
step "Creating launcher $LAUNCHER"
mkdir -p "$BIN_DIR"
{
    echo '#!/usr/bin/env bash'
    echo '# Snapshotter launcher (generated by install.sh)'
    printf 'APP_DIR=%q\n' "$APP_DIR"
    cat <<'EOF'
# Desktop sessions often start with a minimal PATH; add common user-level
# locations so yt-dlp can find a JavaScript runtime (deno/bun).
for dir in "$HOME/.deno/bin" "$HOME/.bun/bin" "$HOME/.local/bin"; do
    case ":$PATH:" in
        *":$dir:"*) ;;
        *) [ -d "$dir" ] && PATH="$PATH:$dir" ;;
    esac
done
export PATH
exec "$APP_DIR/venv/bin/python" "$APP_DIR/main.py" "$@"
EOF
} > "$LAUNCHER"
chmod 755 "$LAUNCHER"
ok "Launcher installed"

# --- 7. Desktop entry and icons ------------------------------------------------
step "Registering with the desktop"
mkdir -p "$DESKTOP_DIR"
# Desktop entries need an absolute path because ~/.local/bin is not always on
# the PATH of the graphical session.
case "$LAUNCHER" in
    *[\"\`\$\\%]*)
        exec_value="$APP_ID"; tryexec_value="$APP_ID"
        warn "Your home path contains special characters; the menu entry relies on ~/.local/bin being on PATH."
        ;;
    *)
        exec_value="\"$LAUNCHER\""; tryexec_value="$LAUNCHER"
        ;;
esac
awk -v exec_value="$exec_value" -v tryexec_value="$tryexec_value" '
    /^Exec=/    { print "Exec=" exec_value; next }
    /^TryExec=/ { print "TryExec=" tryexec_value; next }
    { print }
' "$SRC_DIR/linux/snapshotter.desktop" > "$DESKTOP_FILE"
chmod 644 "$DESKTOP_FILE"
if command -v desktop-file-validate >/dev/null 2>&1; then
    desktop-file-validate "$DESKTOP_FILE" >/dev/null 2>&1 || warn "desktop-file-validate reported issues with $DESKTOP_FILE"
fi
ok "Desktop entry: $DESKTOP_FILE"

install -D -m 644 "$SRC_DIR/assets/icon.svg" "$ICON_ROOT/scalable/apps/$APP_ID.svg"
install -D -m 644 "$SRC_DIR/assets/icon.png" "$ICON_ROOT/256x256/apps/$APP_ID.png"
ok "Icons installed"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q "$DESKTOP_DIR" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1 && [ -f "$ICON_ROOT/index.theme" ]; then
    gtk-update-icon-cache -q -t -f "$ICON_ROOT" 2>/dev/null || true
fi
touch "$ICON_ROOT" 2>/dev/null || true
if command -v xdg-desktop-menu >/dev/null 2>&1; then
    xdg-desktop-menu forceupdate 2>/dev/null || true
fi
ok "Application menu refreshed"

echo
printf '%sSnapshotter is installed.%s\n' "$GREEN$BOLD" "$RESET"
echo "  • Open it from your application menu (search for \"Snapshotter\")"
echo "  • Or run: snapshotter"
case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "    ($BIN_DIR is not on your PATH yet; log out and back in, or use $LAUNCHER)" ;;
esac
echo "  • Uninstall any time with: $APP_DIR/uninstall.sh"
echo "  • The project folder is no longer needed and can be deleted."
