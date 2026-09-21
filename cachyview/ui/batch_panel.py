"""Batch queue panel: build a job, run it, watch per-file progress.

A floating tool window (shown from the main window's Tools menu) where the
user drops files, picks a chain of operations once, and presses Start.  Each
row shows its own status; failures are highlighted but do not stop the run.
"""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                             QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                             QLineEdit, QListWidget, QListWidgetItem,
                             QProgressBar, QPushButton, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from ..backends import batch as b


OPERATIONS = [
    ("PDF → Compress (ebook)", {"tool": "compress", "tier": "ebook"}),
    ("PDF → Rotate 90° CW", {"tool": "rotate", "angle": 90}),
    ("PDF → Rotate 90° CCW", {"tool": "rotate", "angle": -90}),
    ("PDF → OCR (English)", {"tool": "ocr", "language": "eng"}),
    ("PDF → Watermark 'CachyView'", {"tool": "watermark", "text": "CachyView"}),
    ("Image → Rotate 90°", {"tool": "rotate", "angle": 90}),
    ("Image → Grayscale", {"tool": "grayscale"}),
    ("Image → Resize 50%", {"tool": "scale", "factor": 0.5}),
    ("Image → Convert to PNG", {"tool": "convert", "format": "png"}),
    ("Image → Convert to JPEG", {"tool": "convert", "format": "jpeg"}),
]


class BatchPanel(QWidget):
    """A reusable batch-queue widget (also embedded in a dialog)."""

    job_started = pyqtSignal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._job: b.BatchJob | None = None
        self._running = False

        self.files = QListWidget(self)
        self.files.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)

        add_btn = QPushButton("Add files…", self)
        add_btn.clicked.connect(self._add_files)
        clear_btn = QPushButton("Clear", self)
        clear_btn.clicked.connect(self.files.clear)

        self.ops = QComboBox(self)
        for label, _ in OPERATIONS:
            self.ops.addItem(label)
        add_op_btn = QPushButton("Add operation", self)
        add_op_btn.clicked.connect(self._add_op)
        self.op_list = QListWidget(self)

        self.out_dir = QLabel("Output: next to each file", self)
        out_btn = QPushButton("Choose output folder…", self)
        out_btn.clicked.connect(self._choose_out)
        self.rename = QLineEdit(self)
        self.rename.setPlaceholderText(
            "Rename pattern (optional): {name}_edited{ext}, photo_{n}{ext}…")
        self.keep_exif = QCheckBox("Keep EXIF metadata", self)
        self.keep_exif.setChecked(True)

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["File", "Status", "Detail"])
        hdr = self.table.horizontalHeader()
        if hdr is not None:
            hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

        self.progress = QProgressBar(self)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        self.start_btn = QPushButton("Start", self)
        self.start_btn.clicked.connect(self.start)
        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self.cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Files"))
        layout.addWidget(self.files)
        row = QHBoxLayout()
        row.addWidget(add_btn); row.addWidget(clear_btn)
        layout.addLayout(row)

        layout.addWidget(QLabel("Operations (applied in order)"))
        op_row = QHBoxLayout()
        op_row.addWidget(self.ops); op_row.addWidget(add_op_btn)
        layout.addLayout(op_row)
        layout.addWidget(self.op_list)

        layout.addWidget(self.out_dir)
        layout.addWidget(out_btn)
        layout.addWidget(self.rename)
        layout.addWidget(self.keep_exif)
        layout.addWidget(self.table)
        layout.addWidget(self.progress)
        end_row = QHBoxLayout()
        end_row.addWidget(self.start_btn); end_row.addWidget(self.cancel_btn)
        layout.addLayout(end_row)

    # --- building the job -------------------------------------------------
    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Add files to the batch", "",
            "PDF and images (*.pdf *.png *.jpg *.jpeg *.webp *.gif "
            "*.bmp *.tif *.tiff *.avif *.heic)")
        for f in files:
            if not self.files.findItems(f, Qt.MatchFlag.MatchExactly):
                self.files.addItem(f)

    def _add_op(self) -> None:
        label = self.ops.currentText()
        spec = OPERATIONS[self.ops.currentIndex()][1]  # the dict half of the tuple
        item = QListWidgetItem(label)
        item.setData(Qt.ItemDataRole.UserRole, spec)
        self.op_list.addItem(item)

    def _choose_out(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Batch output folder", "")
        if d:
            self._out_dir = Path(d)
            self.out_dir.setText(f"Output: {d}")
        else:
            self._out_dir = None
            self.out_dir.setText("Output: next to each file")

    def _build_job(self) -> b.BatchJob | None:
        if self.files.count() == 0:
            return None
        ops = [self.op_list.item(i).data(Qt.ItemDataRole.UserRole)
               for i in range(self.op_list.count())]
        if not ops:
            return None
        job = b.BatchJob("Batch", ops)
        job.output_dir = getattr(self, "_out_dir", None)
        job.rename_pattern = self.rename.text().strip() or None
        job.keep_exif = self.keep_exif.isChecked()
        for i in range(self.files.count()):
            job.add_file(self.files.item(i).text())
        return job

    # --- running ----------------------------------------------------------
    def start(self) -> None:
        if self._running:
            return
        job = self._build_job()
        if job is None:
            return
        self._job = job
        self._running = True
        self.start_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self._fill_table(job)

        self._handle = b.run_batch_async(job, on_item=self._on_item)
        self._handle.signals.progress.connect(self._on_progress)
        self._handle.signals.finished.connect(lambda _r: self._on_finished())
        self._handle.signals.failed.connect(lambda m, _t: self._on_error(m))
        self.job_started.emit(job)

    def cancel(self) -> None:
        if self._handle is not None:
            self._handle.cancel()

    def _fill_table(self, job: b.BatchJob) -> None:
        self.table.setRowCount(len(job.items))
        for r, item in enumerate(job.items):
            self.table.setItem(r, 0, QTableWidgetItem(item.source.name))
            self.table.setItem(r, 1, QTableWidgetItem("pending"))
            self.table.setItem(r, 2, QTableWidgetItem(""))

    def _on_item(self, item: b.BatchItem) -> None:
        for r in range(self.table.rowCount()):
            name = self.table.item(r, 0)
            if name is not None and name.text() == item.source.name:
                self.table.item(r, 1).setText(item.status)
                self.table.item(r, 2).setText(item.message)
                color = {"done": Qt.GlobalColor.darkGreen,
                         "failed": Qt.GlobalColor.red,
                         "running": Qt.GlobalColor.darkYellow}.get(item.status)
                if color is not None:
                    self.table.item(r, 1).setForeground(color)
                return

    def _on_progress(self, percent: int, message: str) -> None:
        if percent >= 0:
            self.progress.setValue(percent)
        else:
            self.progress.setRange(0, 0)   # indeterminate
            self.progress.reset()

    def _on_finished(self) -> None:
        self._running = False
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        if self._job is not None:
            done = sum(1 for it in self._job.items if it.ok)
            failed = len(self._job.items) - done
            self.progress.setRange(0, 100)
            self.progress.setValue(100)
            self.out_dir.setText(
                f"Finished: {done} done, {failed} failed")
            if failed and self._job.output_dir is not None:
                self.out_dir.setText(
                    f"{self.out_dir.text()} — see {self._job.output_dir}")

    def _on_error(self, message: str) -> None:
        self._running = False
        self.start_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.out_dir.setText(f"Batch error: {message}")


class BatchDialog(QDialog):
    """Standalone batch window launched from the Tools menu."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Batch processing")
        self.resize(640, 560)
        layout = QVBoxLayout(self)
        self.panel = BatchPanel(self)
        layout.addWidget(self.panel)
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        box.rejected.connect(self.reject)
        layout.addWidget(box)
