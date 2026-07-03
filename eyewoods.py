#!/usr/bin/env python3

import sys
import os
import re
import glob
from pathlib import Path
from enum import Enum
from typing import NamedTuple
from datetime import timedelta
import ass
import srt
import tomllib
import subprocess
import polars as pl


from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QStyledItemDelegate,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QLineEdit,
    QHeaderView,
    QFileDialog,
    QScrollArea,
    QFrame,
    QStyle,
    QMenu,
    QStackedWidget,
    QMessageBox,
    QStyleOptionViewItem,
    QTreeView,
    QToolButton,
    QSpinBox,
    QCheckBox,
)
from PySide6.QtCore import (
    Qt,
    QTimer,
    QSize,
    QEvent,
    QThread,
    Signal,
    QSettings,
    QItemSelectionModel,
    QItemSelection,
)
from PySide6.QtGui import (
    QTextDocument,
    QTextDocumentFragment,
    QAction,
    QKeySequence,
    QPainter,
    QStandardItemModel,
    QStandardItem,
)


QUERY_MATCH_TEXT = "#ef5f5f"
COMMENT_TEXT = "rgba(255,255,255,0.3)"
ACTOR_TEXT = "rgba(255,255,255,0.5)"


class SubtitleSource(Enum):
    ASS = "ass"
    SRT = "srt"


class SubTrack(NamedTuple):
    name: str = ""
    pattern: str = ""
    comments_on: bool = True
    time_shift: float = 0


class ProjectConfig:
    def __init__(
        self,
        path: str = "",
        video_pattern: str = "",
        max_ep: int | None = None,
        tracks: list[SubTrack] = [],
    ) -> None:
        self.path = path
        self.video_pattern = video_pattern
        self.max_ep = max_ep
        self.tracks = tracks

    @classmethod
    def from_file(cls, file):
        with open(file, "rb") as f:
            config_dict = tomllib.load(f)
        os.chdir(os.path.dirname(os.path.abspath(file)))
        root_path = config_dict.get("root_path", "")
        video_pattern = config_dict.get("video_glob", "")
        max_ep = config_dict.get("max_ep", None)
        tracks = config_dict.get("tracks", [])
        tracks = [
            SubTrack(
                name=track.get("name", ""),
                pattern=track.get("glob", ""),
                comments_on=track.get("comments_on", True),
                time_shift=track.get("time_shift", 0),
            )
            for track in tracks
        ]
        return cls(
            path=root_path, video_pattern=video_pattern, max_ep=max_ep, tracks=tracks
        )

    def get_track_names(self) -> list:
        names = []
        for track in self.tracks:
            if track.name not in names:
                names.append(track.name)
        return names


# ─── Helpers ──────────────────────────────────────────────────────────────────


def get_int_or(value, default):
    try:
        return int(value)
    except ValueError:
        return default


def resolve_pattern(root_dir: str, pattern: str, max_ep: int) -> list:
    """Return sorted list of files matched by pattern."""
    # Escape [ and ] because we don't want to glob character classes
    pattern = re.sub(r"([\[\]])", r"[\1]", pattern)
    try:
        matches = sorted(
            glob.glob(
                "**/" + pattern, root_dir=os.path.expanduser(root_dir), recursive=True
            )
        )
    except Exception:
        return []
    return [
        p
        for p in matches
        if os.path.isfile(os.path.join(os.path.expanduser(root_dir), p))
        and (not max_ep or get_int_or(str(Path(p).parent), -1) <= max_ep)
    ]


def resolve_episode_pattern(root_dir: str, pattern: str, episode: str) -> str | None:
    # Escape [ and ] because we don't want to glob character classes
    pattern = re.sub(r"([\[\]])", r"[\1]", pattern)
    try:
        matches = glob.glob(
            episode + "/" + pattern,
            root_dir=os.path.expanduser(root_dir),
            recursive=False,
        )
        result = matches[0]
    except Exception:
        return None
    return result


def setFilePreview(label: QLabel, pattern: str, project_config: ProjectConfig):
    if not pattern:
        label.setText("")
        return
    files = resolve_pattern(project_config.path, pattern, project_config.max_ep)
    if not files:
        label.setStyleSheet("color: #e05c5c;")
        label.setText("  ✗ no files matched")
    else:
        label.setStyleSheet("color: #4ecb71;")
        shown = files[:4]
        text = "  ✓ " + "  │  ".join(os.path.basename(p) for p in shown)
        if len(files) > 4:
            text += f"  … +{len(files) - 4} more"
        label.setText(f"{text}   ({len(files)} file{'s' if len(files) != 1 else ''})")


# ─── Page 1: File Selection ───────────────────────────────────────────────────


class PathRowWidget(QWidget):
    remove_requested = Signal(object)

    def __init__(self, project_config, track, parent=None):
        super().__init__(parent)
        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(350)
        self._debounce.timeout.connect(self.update_preview)

        self.project_config = project_config
        self.track = track

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        TOP_HEIGHT = 32

        top = QHBoxLayout()
        top.setSpacing(6)
        top.setContentsMargins(0, 0, 0, 0)
        self.file_line = QLineEdit(self.track.pattern)
        self.file_line.setPlaceholderText("ShowName * Dialogue.ass")
        self.file_line.setFixedHeight(TOP_HEIGHT)
        self.file_line.textChanged.connect(self._debounce.start)
        top.addWidget(self.file_line)

        self.track_name = QLineEdit(self.track.name)
        self.track_name.setPlaceholderText("Track Name")
        self.track_name.setFixedHeight(TOP_HEIGHT)
        self.track_name.setFixedWidth(130)
        top.addWidget(self.track_name)

        self.comment_toggle = QAction("{\\t}")
        self.comment_toggle.setCheckable(True)
        self.comment_toggle.setChecked(self.track.comments_on)
        comment_btn = QToolButton()
        comment_btn.setDefaultAction(self.comment_toggle)
        comment_btn.setFixedSize(44, TOP_HEIGHT)
        top.addWidget(comment_btn)

        remove_action = QAction("x")
        remove_action.triggered.connect(lambda: self.remove_requested.emit(self))
        remove_btn = QToolButton()
        remove_btn.setDefaultAction(remove_action)
        remove_btn.setObjectName("danger")
        remove_btn.setFixedSize(44, TOP_HEIGHT)
        top.addWidget(remove_btn)
        layout.addLayout(top)

        self.preview = QLabel()
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview)

    def update_preview(self):
        pattern = self.file_line.text().strip()
        setFilePreview(self.preview, pattern, self.project_config)

    def get_track_info(self):
        self.track = self.track._replace(
            name=self.track_name.text().strip(),
            pattern=self.file_line.text().strip(),
            comments_on=self.comment_toggle.isChecked(),
        )
        return self.track


class FileSelectionPage(QWidget):
    confirm_requested = Signal()

    def __init__(self, project_config, parent=None):
        super().__init__(parent)
        self._rows = []
        self.project_config = project_config

        self._debounce = QTimer()
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(1000)
        self._debounce.timeout.connect(self._update_project_config)

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(0)

        hdr = QLabel("PROJECT CONFIGURATION")
        hdr.setObjectName("heading")
        root.addWidget(hdr)
        root.addSpacing(10)

        hint_frame = QFrame()
        hint_frame.setObjectName("card")
        hint_layout = QVBoxLayout(hint_frame)
        hint_layout.setContentsMargins(14, 10, 14, 10)
        hint = QLabel(
            "<b>Wildcard syntax: </b><code>?</code> matches any character, <code>*</code> matches any number of characterrs in track file names"
        )
        hint.setTextFormat(Qt.TextFormat.RichText)
        hint.setWordWrap(True)
        hint.setObjectName("hint")
        hint_layout.addWidget(hint)
        root.addWidget(hint_frame)
        root.addSpacing(16)

        top_config = QGridLayout()
        top_config.setHorizontalSpacing(10)
        top_config.setVerticalSpacing(5)

        path_heading = QLabel("Project path")
        path_heading.setObjectName("subheading")
        top_config.addWidget(path_heading, 0, 0)

        self.project_path = QLineEdit(self.project_config.path)
        self.project_path.setPlaceholderText("/path/to/your/project/")
        self.project_path.setToolTip("The root folder in which to search for files.")
        self.project_path.setFixedHeight(32)
        self.project_path.textChanged.connect(self._debounce.start)
        top_config.addWidget(
            self.project_path, 1, 0, alignment=Qt.AlignmentFlag.AlignTop
        )

        max_ep_label = QLabel("Maximum episode")
        max_ep_label.setObjectName("subheading")
        top_config.addWidget(max_ep_label, 0, 1)

        self.max_ep = QLineEdit(str(self.project_config.max_ep or ""))
        self.max_ep.setPlaceholderText("Applies to any purely numeric episode path")
        self.max_ep.setToolTip(
            "Exclude any episode path that can be parsed as a number and is above this value."
        )
        self.max_ep.setFixedHeight(32)
        self.max_ep.textChanged.connect(self._debounce.start)
        top_config.addWidget(self.max_ep, 1, 1, alignment=Qt.AlignmentFlag.AlignTop)
        top_config.setRowMinimumHeight(1, 42)

        video_heading = QLabel("Video pattern")
        video_heading.setObjectName("subheading")
        top_config.addWidget(video_heading, 2, 0)

        self.video_edit_box = QLineEdit(self.project_config.video_pattern)
        self.video_edit_box.setPlaceholderText("ShowName *.mkv")
        self.video_edit_box.setToolTip(
            "Pattern for video files to use when playing corresponding clips in search result. Must be in same folders as sub files."
        )
        self.video_edit_box.setFixedHeight(32)
        self.video_edit_box.textChanged.connect(self._debounce.start)
        top_config.addWidget(
            self.video_edit_box, 3, 0, 1, 2, alignment=Qt.AlignmentFlag.AlignTop
        )

        self.video_file_preview = QLabel()
        self.video_file_preview.setWordWrap(True)
        top_config.addWidget(
            self.video_file_preview, 4, 0, 1, 2, alignment=Qt.AlignmentFlag.AlignTop
        )

        root.addLayout(top_config)
        root.addSpacing(15)

        track_heading = QLabel("Track files")
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
        self.confirm_btn.clicked.connect(self.confirm)
        bar.addWidget(self.confirm_btn)

        root.addLayout(bar)

        for track in self.project_config.tracks:
            self._add_row(track=track)
        self.update_previews()

    def set_config(self, config):
        self.project_config = config
        self.project_path.setText(self.project_config.path)
        self.max_ep.setText(str(self.project_config.max_ep or ""))
        self.video_edit_box.setText(self.project_config.video_pattern)
        for row in self._rows:
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows = []
        for track in self.project_config.tracks:
            self._add_row(track=track)
        self.confirm_btn.setEnabled(len(self._rows) > 0)

    def _add_row(self, checked=False, track=SubTrack()):
        row = PathRowWidget(
            self.project_config,
            track=track,
            parent=self,
        )
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

    def update_previews(self):
        setFilePreview(
            self.video_file_preview,
            self.project_config.video_pattern,
            self.project_config,
        )
        for row in self._rows:
            row.update_preview()

    def _update_project_config(self):
        self.project_config.path = self.project_path.text().strip()
        self.project_config.max_ep = get_int_or(self.max_ep.text().strip(), None)
        self.project_config.video_pattern = self.video_edit_box.text().strip()
        self.update_previews()

    def confirm(self):
        self.confirm_btn.setText("Loading…")
        self.confirm_btn.setEnabled(False)
        self.project_config.path = self.project_path.text().strip()
        self.project_config.max_ep = get_int_or(self.max_ep.text().strip(), None)
        self.project_config.video_pattern = self.video_edit_box.text().strip()
        self.project_config.tracks = []
        for row in self._rows:
            self.project_config.tracks.append(row.get_track_info())
        self.confirm_requested.emit()


# ─── Page 2: Search ───────────────────────────────────────────────────────────

MATCH_ID_ROLE = Qt.ItemDataRole.UserRole + 1


class ResultTreeView(QTreeView):
    play_line_id = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)

        self.copy_action = QAction("&Copy", self)
        self.copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self.copy_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.copy_action.triggered.connect(self.copy_selection)
        self.copy_action.setShortcutVisibleInContextMenu(True)
        self.addAction(self.copy_action)

        self.play_action = QAction("&Play", self)
        self.play_action.setShortcut(QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_P))
        self.play_action.setShortcutContext(Qt.ShortcutContext.WidgetShortcut)
        self.play_action.triggered.connect(self._play_line)
        self.play_action.setShortcutVisibleInContextMenu(True)
        self.addAction(self.play_action)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction(self.copy_action)
        menu.addAction(self.play_action)
        menu.exec(event.globalPos())

    def _play_line(self):
        index = self.selectionModel().currentIndex()
        if not index:
            return
        if index.model().hasChildren(index.siblingAtColumn(0)):
            return

        match_id = index.siblingAtColumn(0).data(MATCH_ID_ROLE)
        self.play_line_id.emit(match_id)

    def copy_selection(self):
        index = self.selectionModel().currentIndex()
        if not index:
            return

        docFrag = QTextDocumentFragment.fromHtml(index.data())
        QApplication.clipboard().setText(docFrag.toPlainText())


class TreeSelectionModel(QItemSelectionModel):
    def select(self, selection, command):
        # Normalize to a single index
        if isinstance(selection, QItemSelection):
            indexes = selection.indexes()
            if not indexes:
                super().select(selection, command)
                return
            index = indexes[0]
        else:
            index = selection

        if not index.isValid():
            super().select(selection, command)
            return

        # If the item in the leftmost column has children, select the whole row
        if index.model().hasChildren(index.siblingAtColumn(0)):
            command |= QItemSelectionModel.SelectionFlag.Rows

        super().select(selection, command)


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
        painter.setClipRect(0, 0, option.rect.width(), option.rect.height())
        doc.drawContents(painter)

        painter.restore()

    def sizeHint(self, option, index):
        self.initStyleOption(option, index)
        doc = QTextDocument()
        doc.setHtml(option.text)
        # Make sure we don't line break the first two columns
        if index.column() >= 2:
            col_width = option.widget.columnWidth(index.column())
        else:
            col_width = -1
        doc.setTextWidth(col_width)
        return QSize(int(doc.idealWidth()), int(doc.size().height()))


class PolarsTreeModel(QStandardItemModel):
    def __init__(self, empty_df, project_config, parent=None):
        super().__init__(parent)
        self._empty_df = empty_df
        self._project_config = project_config
        self.set_dataframe(self._empty_df)

    def _get_or_create_path(self, episode: str, row_width: int) -> QStandardItem:
        """
        Walk (and create if needed) the chain of items for each
        slash-separated segment, returning the deepest one.
        """
        segments = episode.split("/")
        parent = self.invisibleRootItem()

        for segment in segments:
            item = self._find_child(parent, segment)
            if item is None:
                item = QStandardItem(segment)
                row = [item] + [QStandardItem() for _ in range(row_width - 1)]
                parent.appendRow(row)
            parent = item

        return parent

    def set_dataframe(self, df: pl.DataFrame | None) -> None:
        """Replace the displayed DataFrame and refresh the view."""
        self.clear()
        self.layoutAboutToBeChanged.emit()
        self.beginResetModel()

        if df is None:
            df = self._empty_df

        episode_col = "episode"
        headers = ["Episode", "Timestamp"] + self._project_config.get_track_names()
        self.setHorizontalHeaderLabels(headers)

        for episode in df[episode_col].unique(maintain_order=True):
            parent_item = self._get_or_create_path(episode, len(headers))

            for df_row in (
                df.filter(pl.col(episode_col) == episode)
                .select(
                    ["match_id", "timestamp"] + self._project_config.get_track_names()
                )
                .iter_rows()
            ):
                match_id, *row = df_row
                head_item = QStandardItem()
                head_item.setData(match_id, MATCH_ID_ROLE)
                child_row = [head_item] + [QStandardItem(v) for v in row]
                parent_item.appendRow(child_row)
        self.endResetModel()
        self.layoutChanged.emit()

    @staticmethod
    def _find_child(parent: QStandardItem, text: str) -> QStandardItem | None:
        """Return the first col-0 child whose text matches, or None."""
        for row in range(parent.rowCount()):
            child = parent.child(row, 0)
            if child and child.text() == text:
                return child
        return None


class SearchPage(QWidget):
    def __init__(self, project_config, event_df, parent=None):
        super().__init__(parent)
        self._project_config = project_config
        self._event_df = event_df

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(0)

        settings = QSettings()

        TOOLBAR_HEIGHT = 36
        self._toolbar = QHBoxLayout()

        self.regex_toggle = QAction(".*")
        self.regex_toggle.setCheckable(True)
        regex_shorcut = QKeySequence(Qt.Modifier.ALT | Qt.Modifier.CTRL | Qt.Key.Key_R)
        self.regex_toggle.setShortcut(regex_shorcut)
        self.regex_toggle.setToolTip(
            f"Regular expression ({regex_shorcut.toString(QKeySequence.SequenceFormat.NativeText)})"
        )
        self.regex_toggle.setChecked(settings.value("search/regex", False))
        self.regex_toggle.triggered.connect(
            lambda checked: settings.setValue("search/regex", checked)
        )
        self.regex_toggle.triggered.connect(self._run_search)
        regex_btn = QToolButton()
        regex_btn.setDefaultAction(self.regex_toggle)
        regex_btn.setFixedSize(TOOLBAR_HEIGHT, TOOLBAR_HEIGHT)
        self._toolbar.addWidget(regex_btn)
        self._toolbar.addSpacing(10)

        self.case_toggle = QAction("Aa")
        self.case_toggle.setCheckable(True)
        case_shorcut = QKeySequence(Qt.Modifier.ALT | Qt.Modifier.CTRL | Qt.Key.Key_C)
        self.case_toggle.setShortcut(case_shorcut)
        self.case_toggle.setToolTip(
            f"Case sensitive ({case_shorcut.toString(QKeySequence.SequenceFormat.NativeText)})"
        )
        self.case_toggle.setChecked(settings.value("search/case", False))
        self.case_toggle.triggered.connect(
            lambda checked: settings.setValue("search/case", checked)
        )
        self.case_toggle.triggered.connect(self._run_search)
        case_btn = QToolButton()
        case_btn.setDefaultAction(self.case_toggle)
        case_btn.setFixedSize(TOOLBAR_HEIGHT, TOOLBAR_HEIGHT)
        self._toolbar.addWidget(case_btn)
        self._toolbar.addSpacing(10)

        self.word_toggle = QAction("“”")
        self.word_toggle.setCheckable(True)
        word_shorcut = QKeySequence(Qt.Modifier.ALT | Qt.Modifier.CTRL | Qt.Key.Key_W)
        self.word_toggle.setShortcut(word_shorcut)
        self.word_toggle.setToolTip(
            f"Whole word ({word_shorcut.toString(QKeySequence.SequenceFormat.NativeText)})"
        )
        self.word_toggle.setChecked(settings.value("search/word", False))
        self.word_toggle.triggered.connect(
            lambda checked: settings.setValue("search/word", checked)
        )
        self.word_toggle.triggered.connect(self._run_search)
        word_btn = QToolButton()
        word_btn.setDefaultAction(self.word_toggle)
        word_btn.setFixedSize(TOOLBAR_HEIGHT, TOOLBAR_HEIGHT)
        self._toolbar.addWidget(word_btn)
        self._toolbar.addSpacing(10)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Type to search…")
        self._search_box.setFixedHeight(TOOLBAR_HEIGHT)
        self._search_box.textChanged.connect(self._run_search)
        self._toolbar.addWidget(self._search_box)
        self._toolbar.addSpacing(10)

        self.context_box = QSpinBox()
        self.context_box.setFixedSize(40, TOOLBAR_HEIGHT)
        self.context_box.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.context_box.setToolTip("Show X lines before and after each match.")
        self.context_box.valueChanged.connect(self._run_search)
        self._toolbar.addWidget(self.context_box)

        root.addLayout(self._toolbar)
        root.addSpacing(20)

        empty_model_data = {"episode": [], "timestamp": []}
        for name in self._project_config.get_track_names():
            empty_model_data[name] = []
        empty_df = pl.DataFrame(empty_model_data)

        self._model = PolarsTreeModel(empty_df, self._project_config)
        self._model.modelReset.connect(self._apply_column_sizing)
        self.tree = ResultTreeView()
        self.tree.setItemDelegate(ResultItemDelegate())
        self.tree.setModel(self._model)
        self.tree.setSelectionModel(TreeSelectionModel(self._model))
        self.tree.setSelectionBehavior(QTreeView.SelectionBehavior.SelectItems)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.tree.header().setMinimumSectionSize(0)
        self.tree.header().setSectionsMovable(False)
        self.tree.setWordWrap(True)
        self.tree.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self._apply_column_sizing()
        self.tree.setSortingEnabled(True)
        self.tree.setAlternatingRowColors(True)

        root.addWidget(self.tree, 1)

        QTimer.singleShot(0, self._search_box.setFocus)

        self.tree.play_line_id.connect(
            self._play_line_id, type=Qt.ConnectionType.QueuedConnection
        )

    def _set_event_df(self, event_df):
        self._event_df = event_df
        self._run_search()

    def reload_event_df(self):
        self.worker = DataWorker(self._project_config)
        self.worker.done.connect(self._set_event_df)
        self.worker.start()

    def _apply_column_sizing(self):
        episode_doc = QTextDocument()
        episode_doc.setHtml("Episode")
        episode_width = episode_doc.idealWidth()
        for ep in self._event_df["episode"].unique():
            episode_doc.setHtml(ep)
            if episode_doc.idealWidth() > episode_width:
                episode_width = episode_doc.idealWidth()
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(0, int(episode_width) + 16)

        time_doc = QTextDocument()
        time_doc.setHtml("Timestamp")
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.setColumnWidth(1, int(time_doc.idealWidth()) + 16)

    def closeEvent(self, event):
        try:
            self.worker.quit()
            self.worker.wait()
        except AttributeError:
            pass
        super().closeEvent(event)

    def _play_line_id(self, match_id):
        if not self._project_config.video_pattern:
            return
        self.tree.play_action.setEnabled(False)
        row = self._event_df.filter(pl.col("id") == match_id).head(1)
        episode = row["episode"].item()
        context_range = self.context_box.value()
        if context_range > 0:
            episode_ids = self._event_df.filter(pl.col("episode") == episode)["id"]
            start_id = max(int(match_id) - self.context_box.value(), episode_ids.min())
            end_id = min(int(match_id) + self.context_box.value(), episode_ids.max())
        else:
            start_id = match_id
            end_id = match_id
        start_row = self._event_df.filter(pl.col("id") == start_id).head(1)
        end_row = self._event_df.filter(pl.col("id") == end_id).head(1)
        start = start_row["start"].item().total_seconds()
        end = end_row["end"].item().total_seconds()
        relative_video = resolve_episode_pattern(
            self._project_config.path, self._project_config.video_pattern, episode
        )

        errorMessageBox = QMessageBox(self)
        errorMessageBox.setText("Could not play selected line")
        if relative_video is None:
            errorMessageBox.setInformativeText(
                f"Unable to find video: {episode + '/' + self._project_config.video_pattern}"
            )
            errorMessageBox.exec()
        else:
            absolute_video = os.path.abspath(
                os.path.join(self._project_config.path, relative_video)
            )
            mpv_command = QSettings().value("prefs/mpv", "") or "mpv"
            try:
                subprocess.run(
                    mpv_command.split(" ")
                    + [
                        f"--start={start}",
                        f"--end={end}",
                        "--keep-open=no",
                        "--really-quiet",
                        "--sub=no",
                        absolute_video,
                    ]
                )
            except FileNotFoundError:
                errorMessageBox.setInformativeText(
                    f"Unable to find command: {mpv_command}"
                )
                errorMessageBox.exec()
        self.tree.play_action.setEnabled(True)

    def _run_search(self):
        query = self._search_box.text().strip()

        if len(query) == 0:
            self._model.set_dataframe(None)
            return

        # Modify query for search settings
        query_with_settings = query
        if not self.regex_toggle.isChecked():
            query_with_settings = re.escape(query_with_settings)
        if self.word_toggle.isChecked():
            query_with_settings = r"\b" + query_with_settings + r"\b"
        query_with_settings = "(" + query_with_settings + ")"
        if not self.case_toggle.isChecked():
            query_with_settings = r"(?i)" + query_with_settings

        context_range = self.context_box.value()

        # Get the window of surrounding context lines
        event_df = self._event_df.lazy()
        rolling_groups = event_df.with_columns(pl.col("id").alias("match_id")).rolling(
            index_column="match_id",
            period=f"{context_range * 2 + 1}i",
            offset=f"{-context_range}i",
            closed="left",
        )
        rolling_df = pl.concat(
            [
                rolling_groups.all(),
                event_df.select(pl.col("text").alias("match_text")),
            ],
            how="horizontal",
        )

        # Find matches
        matches_df = (
            rolling_df.filter(pl.col("match_text").str.contains(query_with_settings))
            .drop("match_text")
            .explode(pl.exclude("match_id"))
            .unique(subset=["id", "overlap_id"], keep="first")
        )

        # Escape HTML since we'll be rendering it
        for prefix in ["", "overlap_"]:
            matches_df = matches_df.with_columns(
                pl.col(prefix + "text")
                .str.replace_all("&", "&amp;", literal=True)
                .str.replace_all("<", "&lt;", literal=True)
                .str.replace_all(">", "&gt;", literal=True)
                .str.replace_all('"', "&quot;", literal=True)
                .str.replace_all("'", "&#39;", literal=True)
            )

        # Highlight search term
        matches_df = matches_df.with_columns(
            pl.col("text").str.replace_all(
                query_with_settings,
                f"<span style='color:{QUERY_MATCH_TEXT};font-weight:bold;'>$1</span>",
            )
        )

        for prefix in ["", "overlap_"]:
            # Remove comment lines where specified
            matches_df = matches_df.remove(
                pl.col(prefix + "is_comment") & ~pl.col(prefix + "comments_on")
            )
            # Style comment lines
            matches_df = matches_df.with_columns(
                pl.when(pl.col(prefix + "is_comment"))
                .then(
                    pl.lit(f"<span style='color:{COMMENT_TEXT}'>")
                    + pl.col(prefix + "text")
                    + pl.lit("</span>")
                )
                .otherwise(prefix + "text")
                .alias(prefix + "text")
            )

            # Style ASS linebreaks/spaces
            matches_df = matches_df.with_columns(
                pl.when(pl.col(prefix + "sub_source") == SubtitleSource.ASS.value)
                .then(
                    pl.col(prefix + "text").str.replace_all(
                        r"(\\[Nnh])",
                        f"<span style='color:{COMMENT_TEXT}'>$1</span>",
                    )
                )
                .otherwise(prefix + "text")
            )

            # If search term doesn't contain curly braces
            if "{" not in query and "}" not in query:
                # Remove ass comments where specified
                matches_df = matches_df.with_columns(
                    pl.when(
                        (pl.col(prefix + "sub_source") == SubtitleSource.ASS.value)
                        & ~pl.col(prefix + "comments_on")
                    )
                    .then(
                        pl.col(prefix + "text").str.replace_all(
                            r"(\{[^}]*?\})",
                            "",
                        )
                    )
                    .otherwise(prefix + "text")
                )

                # Style ass comment/tag blocks only i
                matches_df = matches_df.with_columns(
                    pl.when(pl.col(prefix + "sub_source") == SubtitleSource.ASS.value)
                    .then(
                        pl.col(prefix + "text").str.replace_all(
                            r"(\{[^}]*?\})",
                            f"<span style='color:{COMMENT_TEXT}'>$1</span>",
                        )
                    )
                    .otherwise(prefix + "text")
                )
            # Add actor if present
            matches_df = matches_df.with_columns(
                pl.when(pl.col(prefix + "actor").cat.len_chars() > 0)
                .then(
                    pl.lit(f"<span style='color:{ACTOR_TEXT}'>(")
                    + pl.col(prefix + "actor")
                    + pl.lit(")</span> ")
                    + pl.col(prefix + "text")
                )
                .otherwise(prefix + "text")
                .alias(prefix + "text")
            )

        # Merge match_id (and thus result row) if results are within context distance
        matches_df = matches_df.sort("match_id").with_columns(
            pl.col("match_id")
            .first()
            .over(
                (pl.col("match_id").diff().abs().fill_null(0) > context_range).cum_sum()
            )
        )

        # Pivot matched text into track columns
        match_pivot = (
            matches_df.unique(subset=["match_id", "id"])
            .sort("id")
            .group_by("match_id")
            .agg(pl.col("text").str.join("<br/>"), pl.col("track").first())
            .pivot(
                "track",
                on_columns=self._project_config.get_track_names(),
                index=["match_id"],
                values="text",
                aggregate_function=None,
            )
        )

        # Pivot overlap text into track columns
        overlap_pivot = (
            matches_df.unique(subset="overlap_id")
            .sort("overlap_id")
            .group_by(["match_id", "overlap_track"])
            .agg(pl.col("overlap_text").str.join("<br/>"))
            .pivot(
                "overlap_track",
                on_columns=self._project_config.get_track_names(),
                index="match_id",
                values="overlap_text",
                aggregate_function=None,
            )
        )

        # Merge pivots
        merged_df = (
            matches_df.filter(pl.col("id") == pl.col("match_id"))
            .unique(subset="match_id")
            .select(["match_id", "episode", "timestamp"])
            .join(
                match_pivot,
                on="match_id",
            )
            .update(overlap_pivot, on="match_id", how="full")
            .sort("match_id")
        )

        try:
            collected_df = merged_df.collect()
        except pl.exceptions.ComputeError:
            # Don't update the model if the query provided an invalid regex
            return

        self._model.set_dataframe(collected_df)

        if collected_df.height < 100:
            self.tree.expandAll()


# ─── Main window ──────────────────────────────────────────────────────────────


class DataWorker(QThread):
    done = Signal(object)

    def __init__(self, project_config):
        super().__init__()
        self.project_config = project_config

    def _load_data(self):
        root_path = Path(os.path.expanduser(self.project_config.path))
        all_events = []
        for i, track in enumerate(self.project_config.tracks):
            shift_delta = timedelta(seconds=track.time_shift)
            paths = [
                Path(p)
                for p in resolve_pattern(
                    self.project_config.path, track.pattern, self.project_config.max_ep
                )
            ]
            for path in paths:
                episode_path = str(path.parent)
                try:
                    with open(root_path / path, encoding="utf_8_sig") as f:
                        if path.suffix == ".ass":
                            parsed_ass = ass.parse(f)
                            for line_index, event in enumerate(parsed_ass.events):
                                all_events.append(
                                    (
                                        event.start + shift_delta,
                                        event.end + shift_delta,
                                        event.text,
                                        line_index,
                                        episode_path,
                                        track.name,
                                        event.name,
                                        event.TYPE == "Comment",
                                        SubtitleSource.ASS.value,
                                        track.comments_on,
                                    )
                                )
                        elif path.suffix == ".srt":
                            parsed_srt = srt.parse(f)
                            for line_index, event in enumerate(parsed_srt):
                                all_events.append(
                                    (
                                        event.start + shift_delta,
                                        event.end + shift_delta,
                                        event.content,
                                        line_index,
                                        episode_path,
                                        track.name,
                                        None,
                                        False,
                                        SubtitleSource.SRT.value,
                                        track.comments_on,
                                    )
                                )
                        else:
                            print(f"Unrecognized file type for {path}")
                            pass
                except Exception as err:
                    print(f"Exception {err=} trying to open {path}")
                    pass

        event_df = pl.LazyFrame(
            all_events,
            schema={
                "start": pl.Duration("ms"),
                "end": pl.Duration("ms"),
                "text": pl.String,
                "line_index": pl.Int32,
                "episode": pl.Categorical(
                    pl.Categories(name="episode", physical=pl.UInt16)
                ),
                "track": pl.Enum(self.project_config.get_track_names()),
                "actor": pl.Categorical(
                    pl.Categories(name="actor", physical=pl.UInt16)
                ),
                "is_comment": pl.Boolean,
                "sub_source": pl.Enum(SubtitleSource),
                "comments_on": pl.Boolean,
            },
            orient="row",
        )
        # Give a unique index to every event
        event_df = event_df.with_row_index("id")
        # Find lines from across tracks that have timing overlap
        overlaps_df = (
            event_df.join(event_df, how="cross")
            .filter(
                (pl.col("track") != pl.col("track_right"))
                & (pl.col("episode") == pl.col("episode_right"))
                & (pl.col("start") <= pl.col("end_right"))
                & (pl.col("start_right") <= pl.col("end"))
            )
            .select(pl.all().name.replace(r"^(.+)_right$", "overlap_$1"))
            .drop(
                [
                    "overlap_start",
                    "overlap_end",
                    "overlap_line_index",
                    "overlap_episode",
                ]
            )
        )

        # Merge overlap lines into the original events to include lines that had no overlap
        # Format timestamps into strings
        event_df = (
            event_df.join(overlaps_df, on="id", how="left")
            .with_columns(pl.col("start").dt.total_seconds().alias("timestamp"))
            .with_columns(
                pl.col("timestamp").map_elements(
                    lambda s: f"{s // 3_600}:{(s % 3_600) // 60:02d}:{(s % 60):02d}",
                    return_dtype=pl.String,
                )
            )
            .sort("id")
            .collect()
        )

        return event_df

    def run(self):
        result = self._load_data()
        self.done.emit(result)


class PreferencesWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.resize(800, 600)
        self.setMinimumSize(640, 480)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        root = QVBoxLayout()
        root.setContentsMargins(20, 20, 20, 20)
        central_widget.setLayout(root)

        header = QLabel("SETTINGS")
        header.setObjectName("heading")
        root.addWidget(header)
        root.addSpacing(10)

        settings = QSettings()

        mpv_label = QLabel("mpv path")
        mpv_label.setObjectName("subheading")
        root.addWidget(mpv_label)

        mpv_path_box = QLineEdit(settings.value("prefs/mpv", ""))
        mpv_path_box.setPlaceholderText("mpv")
        mpv_path_box.textChanged.connect(
            lambda text: settings.setValue("prefs/mpv", text)
        )
        root.addWidget(mpv_path_box)
        root.addSpacing(5)

        auto_load_checkbox = QCheckBox(
            "Immediately load subs when opening a config file"
        )
        auto_load_checkbox.setChecked(settings.value("prefs/auto_load", False))
        auto_load_checkbox.checkStateChanged.connect(
            lambda state: settings.setValue(
                "prefs/auto_load", state == Qt.CheckState.Checked
            )
        )
        root.addWidget(auto_load_checkbox)

        root.addStretch(1)


class MainWindow(QMainWindow):
    def __init__(self, project_config):
        super().__init__()

        self.settings = QSettings()
        self.setWindowTitle(QApplication.applicationName())
        self.resize(self.settings.value("mainwindow/size", QSize(900, 680)))
        self.setMinimumSize(640, 480)

        self._stack = QStackedWidget()
        self.setCentralWidget(self._stack)

        self.project_config = project_config
        self._selection_page = FileSelectionPage(self.project_config)
        self._selection_page.confirm_requested.connect(self._on_confirm)

        self._setup_menu_bar()

        self._stack.addWidget(self._selection_page)

    def _setup_menu_bar(self):
        menu = self.menuBar()

        file_menu = menu.addMenu("&File")

        open_action = QAction("&Open…", self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_file)
        file_menu.addAction(open_action)

        self.close_action = QAction("&Close", self)
        self.close_action.setShortcut(QKeySequence.StandardKey.Close)
        self.close_action.triggered.connect(self._close_action)
        file_menu.addAction(self.close_action)

        self.reload_action = QAction("&Reload", self)
        self.reload_action.setShortcut(Qt.Modifier.CTRL | Qt.Key.Key_R)
        file_menu.addAction(self.reload_action)

        edit_menu = menu.addMenu("&Edit")

        self.copy_action = QAction("&Copy", self)
        self.copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        edit_menu.addAction(self.copy_action)

        edit_menu.addSeparator()

        self.confirm_action = QAction("&Confirm", self)
        self.confirm_action.setShortcut(
            QKeySequence(Qt.Modifier.CTRL | Qt.Key.Key_Return)
        )
        self.confirm_action.triggered.connect(self._selection_page.confirm)
        edit_menu.addAction(self.confirm_action)

        prefs_action = QAction("Preferences…", self)
        prefs_action.setShortcut(QKeySequence.StandardKey.Preferences)
        prefs_action.setMenuRole(QAction.MenuRole.PreferencesRole)
        prefs_action.triggered.connect(self._open_preferences)
        edit_menu.addAction(prefs_action)

        help_menu = menu.addMenu("&Help")

        about_action = QAction(f"About {QApplication.applicationName()}", self)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def _open_preferences(self):
        if not hasattr(self, "_prefs_window") or not self._prefs_window.isVisible():
            self._prefs_window = PreferencesWindow()

        self._prefs_window.show()
        self._prefs_window.raise_()
        self._prefs_window.activateWindow()

    def _on_done_loading(self, event_df):
        search_page = SearchPage(self.project_config, event_df)
        self.copy_action.triggered.connect(search_page.tree.copy_selection)
        self.reload_action.triggered.connect(search_page.reload_event_df)

        self._stack.addWidget(search_page)
        self._stack.setCurrentWidget(search_page)
        self.reload_action.setEnabled(True)

    def _on_confirm(self):
        self.confirm_action.setEnabled(False)
        self.worker = DataWorker(self.project_config)
        self.worker.done.connect(self._on_done_loading)
        self.worker.start()

    def _close_action(self):
        if hasattr(self, "_prefs_window") and self._prefs_window.isVisible():
            self._prefs_window.close()
        elif self._stack.count() > 1:
            self._stack.removeWidget(self._stack.currentWidget())
        else:
            QApplication.quit()

        if self._stack.count() == 1:
            self.reload_action.setEnabled(False)
            self.confirm_action.setEnabled(True)
            self._selection_page.confirm_btn.setText("Confirm  →")

    def load_project_config(self, file):
        self.project_config = ProjectConfig.from_file(file)
        self._selection_page.set_config(self.project_config)
        while self._stack.count() > 1:
            self._stack.removeWidget(self._stack.currentWidget())

        if self._stack.count() == 1:
            self.confirm_action.setEnabled(True)
            self._selection_page.confirm_btn.setText("Confirm  →")

        if self.settings.value("prefs/auto_load", False):
            self._selection_page.confirm()

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open File", "", "Eyewoods config files (*.eyewoods);;All files (*)"
        )
        if path:
            self.load_project_config(path)

    def show_about(self):
        name = QApplication.applicationName()
        version = QApplication.applicationVersion()
        QMessageBox.about(self, f"About {name}", f"{name} {version}")

    def closeEvent(self, event):
        try:
            self.worker.quit()
            self.worker.wait()
        except AttributeError:
            pass
        super().closeEvent(event)

    def resizeEvent(self, event):
        self.settings.setValue("mainwindow/size", event.size())
        super().resizeEvent(event)


class Eyewoods(QApplication):
    file_opened = Signal(str)

    def __init__(self, argv):
        super().__init__(argv)
        if len(argv) > 1:
            self.project_config = ProjectConfig.from_file(argv[1])
        else:
            self.project_config = ProjectConfig()

    def event(self, e):
        if e.type() == QEvent.Type.FileOpen:
            self.file_opened.emit(e.file())
            return True
        return super().event(e)


def main():
    app = Eyewoods(sys.argv)
    app.setOrganizationName("Gonomae")
    app.setApplicationName("Eyewoods")
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        version_path = Path(__file__).resolve().with_name("version.txt")
        with open(version_path, "r") as f:
            version = f.read()
        app.setApplicationVersion(version)
    else:
        app.setApplicationVersion("0.0.0-dev")

    pl.Config.set_engine_affinity("streaming")

    theme_path = Path(__file__).resolve().with_name("theme.toml")
    with open(theme_path, "rb") as f:
        theme = tomllib.load(f)
    style_path = Path(__file__).resolve().with_name("style.qss")
    with open(style_path) as f:
        sheet = f.read().format_map(theme)
        app.setStyleSheet(sheet)

    window = MainWindow(app.project_config)
    app.file_opened.connect(window.load_project_config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
