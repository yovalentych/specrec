"""Look and feel: light and dark themes (colours, Qt style sheet, plot colours).

Design intent: a desktop instrument, not a web page — flat surfaces, thin borders,
small radii, the system UI font, tabular monospaced digits for readouts, native docks
and toolbars. All colours live here so a theme can be changed in one place.
"""
from __future__ import annotations

from dataclasses import dataclass

MONO = '"SF Mono", "Menlo", "Consolas", "DejaVu Sans Mono", monospace'


@dataclass(frozen=True)
class Theme:
    name: str
    bg: str
    surface: str
    surface2: str
    border: str
    text: str
    muted: str
    accent: str
    accent_text: str
    danger: str
    warn: str
    success: str
    plot_bg: str
    plot_fg: str
    grid_alpha: float
    channels: tuple[str, ...]


LIGHT = Theme(
    name="light", bg="#e9ecf0", surface="#f7f8fa", surface2="#ffffff", border="#c9cfd8",
    text="#1a2129", muted="#5f6b7a", accent="#1f63d6", accent_text="#ffffff",
    danger="#cf2e2e", warn="#c26c00", success="#178a45",
    plot_bg="#ffffff", plot_fg="#3b4654", grid_alpha=0.16,
    channels=("#1f63d6", "#cf2e2e", "#178a45", "#c26c00", "#7442c8", "#0a8aa3"),
)

DARK = Theme(
    name="dark", bg="#15191e", surface="#1d2229", surface2="#232a32", border="#343d48",
    text="#e3e8ee", muted="#8c98a7", accent="#4f8cff", accent_text="#ffffff",
    danger="#f05252", warn="#f2a33a", success="#3fbf6e",
    plot_bg="#101418", plot_fg="#aab6c4", grid_alpha=0.2,
    channels=("#5b9dff", "#ff6b6b", "#4fd18b", "#f2b14a", "#a78bfa", "#38c6e0"),
)

THEMES = {"light": LIGHT, "dark": DARK}


def apply_palette(app, t: Theme) -> None:
    """Native palette, so that every widget (also ones the style sheet does not reach:
    scroll-area viewports, dialogs, combo pop-ups) follows the theme."""
    from PySide6.QtGui import QColor, QPalette
    p = QPalette()
    c = QColor
    roles = {
        QPalette.Window: t.surface2, QPalette.WindowText: t.text, QPalette.Base: t.surface2,
        QPalette.AlternateBase: t.surface, QPalette.Text: t.text, QPalette.Button: t.surface2,
        QPalette.ButtonText: t.text, QPalette.Highlight: t.accent, QPalette.HighlightedText: t.accent_text,
        QPalette.ToolTipBase: t.surface2, QPalette.ToolTipText: t.text, QPalette.PlaceholderText: t.muted,
        QPalette.BrightText: t.danger, QPalette.Link: t.accent, QPalette.Mid: t.border,
        QPalette.Dark: t.border, QPalette.Light: t.surface2, QPalette.Midlight: t.surface,
        QPalette.Shadow: t.border,
    }
    for role, col in roles.items():
        p.setColor(role, c(col))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, c(t.muted))
    app.setPalette(p)


def stylesheet(t: Theme) -> str:
    return f"""
    QMainWindow, QDialog {{ background: {t.bg}; }}
    QWidget {{ color: {t.text}; }}
    QMainWindow::separator {{ background: {t.border}; width: 1px; height: 1px; }}

    QMenuBar {{ background: {t.surface}; border-bottom: 1px solid {t.border}; }}
    QMenuBar::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
    QMenu {{ background: {t.surface2}; border: 1px solid {t.border}; padding: 4px; }}
    QMenu::item {{ padding: 5px 22px 5px 22px; }}
    QMenu::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
    QMenu::separator {{ height: 1px; background: {t.border}; margin: 4px 8px; }}

    QToolBar {{ background: {t.surface}; border: none; border-bottom: 1px solid {t.border};
                spacing: 6px; padding: 4px 8px; }}
    QToolBar::separator {{ background: {t.border}; width: 1px; margin: 4px 6px; }}
    QToolButton {{ background: transparent; border: 1px solid transparent; border-radius: 4px;
                   padding: 4px 8px; }}
    QToolButton:hover {{ border-color: {t.border}; background: {t.surface2}; }}
    QToolButton:checked {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; }}
    QToolButton#play {{ background: {t.accent}; color: {t.accent_text}; font-weight: 600; min-width: 74px; }}
    QToolButton#play:disabled {{ background: {t.border}; color: {t.muted}; }}
    QToolButton#record {{ color: {t.danger}; border-color: {t.danger}; font-weight: 600; }}
    QToolButton#record:checked {{ background: {t.danger}; color: white; }}

    #status {{ border-radius: 3px; padding: 3px 8px; font-weight: 600; font-size: 11px; color: white; }}
    #phase {{ font-weight: 600; }}
    #phaseTime, #mono {{ color: {t.muted}; font-family: {MONO}; }}
    #clock {{ font-family: {MONO}; font-size: 20px; font-weight: 600; padding: 0 6px; }}

    QDockWidget {{ titlebar-close-icon: none; }}
    QDockWidget::title {{ background: {t.surface}; padding: 6px 8px; border-bottom: 1px solid {t.border};
                          text-align: left; font-weight: 600; }}
    QDockWidget > QWidget {{ background: {t.surface2}; border: 1px solid {t.border}; border-top: none; }}
    QTabBar::tab {{ background: {t.surface}; border: 1px solid {t.border}; padding: 4px 10px;
                    border-bottom: none; }}
    QTabBar::tab:selected {{ background: {t.surface2}; font-weight: 600; }}

    #hint {{ color: {t.muted}; font-size: 11px; }}
    #section {{ color: {t.muted}; font-size: 11px; font-weight: 600; }}
    #explain {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 3px; }}

    #tile {{ background: {t.surface2}; border: 1px solid {t.border}; border-radius: 3px; }}
    #tileTitle {{ color: {t.muted}; font-size: 11px; }}
    #tileValue {{ font-family: {MONO}; font-size: 20px; font-weight: 600; }}
    #tileUnit {{ color: {t.muted}; font-size: 10px; }}
    #tileDelta {{ font-family: {MONO}; font-size: 11px; font-weight: 600; }}
    #plotFrame {{ background: {t.plot_bg}; border: 1px solid {t.border}; }}

    QPushButton {{ background: {t.surface2}; border: 1px solid {t.border}; border-radius: 4px;
                   padding: 4px 10px; min-height: 18px; }}
    QPushButton:hover {{ border-color: {t.accent}; }}
    QPushButton:pressed {{ background: {t.border}; }}
    QPushButton:disabled {{ color: {t.muted}; }}
    QPushButton:checked {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; }}
    QPushButton#primary {{ background: {t.accent}; color: {t.accent_text}; border-color: {t.accent}; font-weight: 600; }}
    QPushButton#seg {{ border-radius: 0; padding: 4px 8px; }}

    QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {{ background: {t.surface2}; border: 1px solid {t.border};
                 border-radius: 4px; padding: 3px 6px; min-height: 18px; selection-background-color: {t.accent}; }}
    QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {{ border-color: {t.accent}; }}
    QComboBox QAbstractItemView {{ background: {t.surface2}; border: 1px solid {t.border};
                 selection-background-color: {t.accent}; selection-color: {t.accent_text}; }}
    QListWidget {{ background: {t.surface2}; border: 1px solid {t.border}; border-radius: 3px; }}
    QListWidget::item {{ padding: 2px 4px; }}
    QListWidget::item:selected {{ background: {t.accent}; color: {t.accent_text}; }}
    QTableWidget {{ background: {t.surface2}; gridline-color: {t.border}; border: 1px solid {t.border}; }}
    QHeaderView::section {{ background: {t.surface}; border: none; border-right: 1px solid {t.border};
                            border-bottom: 1px solid {t.border}; padding: 4px 6px; font-weight: 600; }}
    QGroupBox {{ border: 1px solid {t.border}; border-radius: 3px; margin-top: 10px; padding-top: 6px; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 4px; color: {t.muted}; }}
    QCheckBox {{ spacing: 6px; }}

    QSlider::groove:horizontal {{ height: 4px; background: {t.border}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: {t.surface2}; border: 1px solid {t.accent};
                                  width: 12px; margin: -5px 0; border-radius: 6px; }}
    QSplitter::handle {{ background: {t.bg}; }}
    QSplitter::handle:vertical {{ height: 6px; }}

    QStatusBar {{ background: {t.surface}; border-top: 1px solid {t.border}; color: {t.muted}; }}
    QToolTip {{ background: {t.surface2}; color: {t.text}; border: 1px solid {t.border}; padding: 4px; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{ width: 9px; background: transparent; }}
    QScrollBar::handle:vertical {{ background: {t.border}; border-radius: 4px; min-height: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
    QScrollBar:horizontal {{ height: 9px; background: transparent; }}
    QScrollBar::handle:horizontal {{ background: {t.border}; border-radius: 4px; min-width: 30px; }}
    """
