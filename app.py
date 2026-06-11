#!/usr/bin/env python3
"""
File Search App — PyQt6
Select files, edit paths with wildcards/number placeholders,
then search their contents with SQLite FTS5.
"""

import sys
import os
import re
import glob
from pathlib import Path
from datetime import timedelta
import argparse
import ass
from typing import Any, Callable, TypedDict
import re
import tomllib
import polars as pl

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QStyledItemDelegate,
    QVBoxLayout, QHBoxLayout, QGridLayout, QTableView,
    QLabel, QPushButton, QLineEdit, QTextEdit, QHeaderView,
    QFileDialog, QScrollArea, QFrame, QStyle,
    QStackedWidget, QProgressDialog,
)
from PyQt6.QtCore import Qt, QTimer, QSize, QEvent, pyqtSignal, QAbstractTableModel, QModelIndex
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon, QTextDocument, QStandardItem


# ─── Palette ──────────────────────────────────────────────────────────────────

DARK_BG      = "#0f1117"
PANEL_BG     = "#171b26"
CARD_BG      = "#1e2231"
BORDER       = "#2a2f42"
ACCENT       = "#4f8ef7"
ACCENT_DIM   = "#2d5ab5"
TEXT_MAIN    = "#e8eaf0"
TEXT_DIM     = "#7a7f94"
TEXT_MATCH   = "#ef5f5f"
DANGER       = "#e05c5c"
SUCCESS      = "#4ecb71"

QSS = f"""
QWidget {{
    background-color: {DARK_BG};
    color: {TEXT_MAIN};
    font-family: "Fira Code";
    font-size: 13px;
}}

QPushButton {{
    background-color: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 16px;
}}
QPushButton:hover {{
    background-color: {ACCENT_DIM};
    border-color: {ACCENT};
}}
QPushButton:pressed {{
    background-color: {ACCENT};
}}
QPushButton#primary {{
    background-color: {ACCENT};
    color: #fff;
    border: none;
    font-weight: bold;
}}
QPushButton#primary:hover {{
    background-color: #6aa0ff;
}}
QPushButton#primary:disabled {{
    background-color: #2a3050;
    color: {TEXT_DIM};
}}
QPushButton#danger {{
    color: {DANGER};
    border-color: {DANGER};
    background-color: transparent;
}}
QPushButton#danger:hover {{
    background-color: {DANGER};
    color: #fff;
}}

QLineEdit {{
    background-color: {CARD_BG};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 3px 10px;
    color: {TEXT_MAIN};
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{
    border-color: {ACCENT};
}}

QScrollArea {{
    border: none;
    background-color: transparent;
}}
QScrollBar:vertical {{
    background: {PANEL_BG};
    width: 8px;
    border-radius: 4px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 4px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {TEXT_DIM};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

QHeaderView::section {{
    border: none;
    background-color: transparent;
}}

QLabel {{
    background-color: transparent;
}}
QLabel#heading {{
    font-size: 18px;
    font-weight: bold;
    color: {TEXT_MAIN};
    letter-spacing: 0.5px;
}}
QLabel#subheading {{
    font-size: 11px;
    color: {TEXT_DIM};
    letter-spacing: 1px;
}}
QLabel#hint {{
    color: {TEXT_DIM};
    font-size: 12px;
}}


"""
class SubtitleEvent:
    def __init__(
        self,
        start: timedelta,
        end: timedelta,
        text: str,
        episode: str,
        track_name: str,
        *,
        actor: str | None = None,
    ) -> None:
        self.start = start
        self.end = end
        self.text = text
        self.episode = episode
        self.track_name = track_name
        self.actor = actor

class ProjectConfig:
    def __init__(
        self,
        path: str = "",
        tracks: list[tuple[[str, str]]] = [], # [("Name", path)]
    ) -> None:
        self.path = path
        self.tracks = tracks

    @classmethod
    def from_dict(cls, data):
        print(data)
        root_path = data.get("root_path", "")
        tracks = data.get("tracks", [])
        tracks = [(track.get("name", ""), track.get("glob", "")) for track in tracks]
        return cls(path=root_path, tracks=tracks)

    def get_track_names(self) -> list:
        names = []
        for name, _ in self.tracks:
            if not name in names:
                names.append(name)
        return names

# ─── Helpers ──────────────────────────────────────────────────────────────────

def resolve_pattern(root_dir: str, pattern: str) -> list:
    """Return sorted list of files matched by pattern."""
    try:
        matches = sorted(glob.glob("**/" + pattern, root_dir=os.path.expanduser(root_dir), recursive=True))
    except Exception:
        return []
    return [p for p in matches if os.path.isfile(os.path.join(os.path.expanduser(root_dir), p))]


# ─── Page 1: File Selection ───────────────────────────────────────────────────

class PathRowWidget(QWidget):
    remove_requested = pyqtSignal(object)

    def __init__(self, project_config, glob=None, track_name=None, parent=None):
        super().__init__(parent)
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(350)
        self._debounce.timeout.connect(self.update_preview)

        self.project_config = project_config

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        top = QHBoxLayout()
        top.setSpacing(6)
        top.setContentsMargins(0, 0, 0, 0)
        self.file_line = QLineEdit(glob)
        self.file_line.setFixedHeight(32)
        self.file_line.textChanged.connect(lambda: self._debounce.start())
        top.addWidget(self.file_line)

        self.track_name = QLineEdit(track_name)
        self.track_name.setFixedHeight(32)
        self.track_name.setFixedWidth(130)
        self.track_name.setPlaceholderText("Track Name")
        top.addWidget(self.track_name)

        self.remove_btn = QPushButton("x")
        self.remove_btn.setObjectName("danger")
        self.remove_btn.setFixedHeight(32)
        # self.remove_btn.setFixedSize(32, 32)
        self.remove_btn.clicked.connect(lambda: self.remove_requested.emit(self))
        top.addWidget(self.remove_btn)
        layout.addLayout(top)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)

        self.update_preview()

    def update_preview(self):
        pattern = self.file_line.text().strip()
        if not pattern:
            self.preview.setText("")
            return
        files = resolve_pattern(self.project_config.path, pattern)
        if not files:
            self.preview.setStyleSheet(f"color: {DANGER};")
            self.preview.setText("  ✗ no files matched")
        else:
            self.preview.setStyleSheet(f"color: {SUCCESS};")
            shown = files[:4]
            text = "  ✓ " + "  │  ".join(os.path.basename(p) for p in shown)
            if len(files) > 4:
                text += f"  … +{len(files) - 4} more"
            self.preview.setText(f"{text}   ({len(files)} file{'s' if len(files)!=1 else ''})")

    def get_file_glob(self):
        return self.file_line.text().strip()

    def get_track_name(self):
        return self.track_name.text().strip()


class FileSelectionPage(QWidget):
    confirm_requested = pyqtSignal()

    def __init__(self, project_config, parent=None):
        super().__init__(parent)
        self._rows = []
        self.project_config = project_config

        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(350)
        self._debounce.timeout.connect(self._update_project_path)

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(0)

        hdr = QLabel("FILE SELECTION")
        hdr.setObjectName("heading")
        root.addWidget(hdr)
        root.addSpacing(10)

        hint_frame = QFrame()
        hint_frame.setObjectName("card")
        hint_layout = QVBoxLayout(hint_frame)
        hint_layout.setContentsMargins(14, 10, 14, 10)
        hint = QLabel(
            "<b>Wildcard syntax:</b>  <code>*</code> matches anything"
        )
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        hint_layout.addWidget(hint)
        root.addWidget(hint_frame)
        root.addSpacing(16)

        path_heading = QLabel("Project Path")
        path_heading.setObjectName("subheading")
        root.addWidget(path_heading)
        root.addSpacing(5)

        self.project_path = QLineEdit(self.project_config.path)
        self.project_path.setFixedHeight(32)
        self.project_path.textChanged.connect(lambda: self._debounce.start())
        root.addWidget(self.project_path)
        root.addSpacing(10)

        track_heading = QLabel("Files")
        track_heading.setObjectName("subheading")
        root.addWidget(track_heading)
        root.addSpacing(5)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(14)
        self._rows_layout.addStretch()

        scroll.setWidget(self._rows_container)
        root.addWidget(scroll, 1)
        root.addSpacing(16)

        bar = QHBoxLayout()
        bar.setSpacing(10)

        add_btn = QPushButton("＋  Add Track")
        add_btn.clicked.connect(self._add_row)
        bar.addWidget(add_btn)

        bar.addStretch()

        self.confirm_btn = QPushButton("Confirm  →")
        self.confirm_btn.setObjectName("primary")
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self._confirm)
        bar.addWidget(self.confirm_btn)

        root.addLayout(bar)

        for (name, glob) in self.project_config.tracks:
            self._add_row(glob=glob, track_name=name)

    def _add_row(self, checked=False, glob=None, track_name=None):
        row = PathRowWidget(self.project_config, glob=glob, track_name=track_name, parent=self)
        row.remove_requested.connect(self._remove_row)
        idx = self._rows_layout.count() - 1
        self._rows_layout.insertWidget(idx, row)
        self._rows.append(row)
        self.confirm_btn.setEnabled(True)

    def _remove_row(self, row):
        if row in self._rows:
            self._rows.remove(row)
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        if len(self._rows) == 0:
            self.confirm_btn.setEnabled(False)

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select files", "", "All files (*.*)")
        for p in paths:
            self._add_row(p)

    def _update_project_path(self):
        self.project_config.path = self.project_path.text().strip()
        for row in self._rows:
            row.update_preview()

    def _confirm(self):
        self.project_config.path = self.project_path.text().strip()
        self.project_config.tracks = []
        for row in self._rows:
            self.project_config.tracks.append((row.get_track_name(), row.get_file_glob()))
        self.confirm_requested.emit()


# ─── Page 2: Search ───────────────────────────────────────────────────────────

class ResultItemDelegate(QStyledItemDelegate):
    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index):
        self.initStyleOption(option, index)
        painter.save()

        doc = QTextDocument()
        doc.setHtml(option.text)
        doc.setTextWidth(option.rect.width())

        # Draw background
        option.text = ""
        option.widget.style().drawControl(
            QStyle.ControlElement.CE_ItemViewItem, option, painter, option.widget
        )

        # Clip and translate painter to cell bounds
        painter.translate(option.rect.topLeft())
        painter.setClipRect(0, 0, option.rect.width(), option.rect.height() )
        doc.drawContents(painter)

        painter.restore()

    def sizeHint(self, option, index):
        self.initStyleOption(option, index)
        doc = QTextDocument()
        doc.setHtml(option.text)
        doc.setTextWidth(option.rect.width())
        return QSize(int(doc.idealWidth()), int(doc.size().height()))

class PolarsTableModel(QAbstractTableModel): 
    def __init__(self, df: pl.DataFrame, parent=None):
        super().__init__(parent)
        self._df = df
 
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else self._df.height
 
    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else self._df.width
 
    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
 
        if role == Qt.ItemDataRole.DisplayRole:
            value = self._df[index.row(), index.column()]
            return str(value) if value is not None else ""
  
        return None
 
    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.ItemDataRole.DisplayRole):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self._df.columns[section]
        return str(section)   # row numbers

    def set_dataframe(self, df: pl.DataFrame) -> None:
        """Replace the displayed DataFrame and refresh the view."""
        self.layoutAboutToBeChanged.emit()
        self.beginResetModel()
        self._df = df
        self.endResetModel()
        self.layoutChanged.emit()


class SearchPage(QWidget):
    def __init__(self, project_config, event_df, parent=None):
        super().__init__(parent)
        self._config = project_config
        self._event_df = event_df

        self._result_widgets = []
        self._exhausted = False

        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(100)
        self._debounce.timeout.connect(self._run_search)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(0)

        heading = QLabel("SEARCH")
        heading.setObjectName("heading")
        root.addWidget(heading)
        root.addSpacing(16)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText(
            'Type to search…'
        )
        self._search_box.setFixedHeight(42)
        self._search_box.textChanged.connect(lambda: self._debounce.start())
        root.addWidget(self._search_box)
        root.addSpacing(20)

        self._model = PolarsTableModel(pl.DataFrame())

        self._table = QTableView()
        self._table.setItemDelegate(ResultItemDelegate())
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setMinimumSectionSize(0)
        self._table.setWordWrap(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._model.layoutChanged.connect(self._table.resizeRowsToContents)
        self._table.setModel(self._model)


        root.addWidget(self._table, 1)

        self._search_box.setFocus()

    # ── search entry point ────────────────────────────────────────────────────

    def _run_search(self):
        query = self._search_box.text().strip()
        if query == "":
            self._model.set_dataframe(pl.DataFrame())
            return
        matches_df = self._event_df.lazy().filter(pl.col("text").str.to_lowercase().str.contains(str.lower(query)))
        matches_df = (matches_df
            .with_columns(pl.col("text").str.replace_all(r"(" + re.escape(query) + ")", f"<span style=\"color:{TEXT_MATCH};font-weight:bold;\">$1</span>"))
            .rename({"episode": "Episode"})
        )

        match_pivot = matches_df.pivot(
            "track_name",
            on_columns=self._config.get_track_names(),
            index=["id", "Episode", "Timestamp"],
            values="text",
            aggregate_function="first"
        )

        overlap_pivot = matches_df.pivot(
            "overlap_track",
            on_columns=self._config.get_track_names(),
            index="id",
            values="overlap_text",
            aggregate_function=pl.when(pl.element().count() > 0).then(pl.element().str.join("<br/>"))
        )

        result_df = match_pivot.update(
            overlap_pivot,
            on="id",
            how="full",
        ).drop("id").collect()

        self._model.set_dataframe(result_df)
        


# ─── Main window ──────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.setWindowTitle("FileSearch")
        self.resize(900, 680)
        self.setMinimumSize(640, 480)

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self.config = config
        self._selection_page = FileSelectionPage(self.config)
        self._selection_page.confirm_requested.connect(self._on_confirm)
        self._stack.addWidget(self._selection_page)

    def _on_confirm(self):
        root_path = Path(os.path.expanduser(self.config.path))
        all_events = []
        for i, (name, glob) in enumerate(self.config.tracks):
            paths = [Path(p) for p in resolve_pattern(self.config.path, glob)]
            for path in paths:
                episode_path = str(path.parent)
                try:
                    with open(root_path / path, encoding='utf_8_sig') as f:
                        if path.suffix == ".ass":
                            parsed_ass = ass.parse(f)
                            for line_index, event in enumerate(parsed_ass.events):
                                all_events.append((
                                    event.start,
                                    event.end,
                                    event.text,
                                    line_index,
                                    episode_path,
                                    name,
                                    event.name
                                ))
                        else:
                            print(f"Unrecognized file type for {path}")
                            pass
                except Exception as err:
                    print(f"Exception {err=} trying to open {path}")
                    pass

        event_df = pl.DataFrame(
            all_events,
            schema={
                "start": pl.Duration("ms"),
                "end": pl.Duration("ms"),
                "text": pl.String,
                "line_index": pl.Int32,
                "episode": pl.String,
                "track_name": pl.String,
                "actor": pl.String,
                },
            orient="row"
        ).lazy()
        event_df = event_df.with_row_index("id")
        overlaps_df = (event_df
            .join(event_df, how="cross")
            .filter(
                (pl.col("track_name") != pl.col("track_name_right")) &
                (pl.col("episode") == pl.col("episode_right")) &
                (pl.col("start") <= pl.col("end_right")) &
                (pl.col("start_right") <= pl.col("end"))
            )
            .rename({"text_right": "overlap_text", "track_name_right": "overlap_track"})
            .select(["id", "overlap_text", "overlap_track"])
        )
        event_df = (event_df
            .join(overlaps_df, on="id", how="left")
            .with_columns(
                pl.col("start").dt.total_seconds().alias("Timestamp")
            )
            .with_columns(
                pl.col("Timestamp").map_elements(
                    lambda s: f"{s // 3_600}:{(s % 3_600) // 60:02d}:{(s % 60):02d}",
                    return_dtype=pl.String
                )
            )
            .collect()
        )

        search_page = SearchPage(self.config, event_df)
        self._stack.addWidget(search_page)
        self._stack.setCurrentWidget(search_page)

    def closeEvent(self, event):
        super().closeEvent(event)

class Eyewoods(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        if len(argv) > 1:
            self.config = self.config_from_file(argv[1])
        else:
            self.config = ProjectConfig()

    def event(self, e):
        if e.type() == QEvent.Type.FileOpen:
            self.files.append(e.file())
            self.open_file(e.file())
            return True
        return super().event(e)

    def config_from_file(self, file):
        with open(file, "rb") as f:
            config_dict = tomllib.load(f)
            return ProjectConfig.from_dict(config_dict)


def main():
    app = Eyewoods(sys.argv)
    app.setStyleSheet(QSS)
    win = MainWindow(app.config)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()