"""Context Manager UI: list, add, edit, delete, activate, default."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.context_manager import (
    VALID_LANGUAGES,
    VALID_RESPONSE_LENGTHS,
    ContextConfig,
    ContextManager,
)
from .widgets import section


class ContextEditDialog(QDialog):
    """Create/edit one context. All fields optional except name."""

    def __init__(self, parent=None, context: ContextConfig | None = None):
        super().__init__(parent)
        self.setWindowTitle("Context" + (" editor" if context else " editor — new"))
        self.setMinimumWidth(520)
        self._original = context
        form = QFormLayout(self)

        self.ed_name = QLineEdit(context.name if context else "")
        self.ed_name.setPlaceholderText("e.g. Programming Context")
        form.addRow("name", self.ed_name)

        self.ed_desc = QLineEdit(context.description if context else "")
        self.ed_desc.setPlaceholderText("short description")
        form.addRow("description", self.ed_desc)

        self.txt_instructions = QPlainTextEdit(context.instructions if context else "")
        self.txt_instructions.setPlaceholderText(
            "system instructions for this context (what the assistant should do)")
        self.txt_instructions.setFixedHeight(110)
        form.addRow("instructions", self.txt_instructions)

        self.txt_knowledge = QPlainTextEdit(context.knowledge if context else "")
        self.txt_knowledge.setPlaceholderText(
            "additional knowledge / notes (facts, versions, preferences)")
        self.txt_knowledge.setFixedHeight(90)
        form.addRow("knowledge", self.txt_knowledge)

        self.cmb_lang = QComboBox()
        for code in VALID_LANGUAGES:
            self.cmb_lang.addItem(code)
        self.cmb_lang.setCurrentText(context.language if context else "auto")
        form.addRow("language", self.cmb_lang)

        self.cmb_len = QComboBox()
        for length in VALID_RESPONSE_LENGTHS:
            self.cmb_len.addItem(length)
        self.cmb_len.setCurrentText(context.response_length if context else "short")
        form.addRow("response length", self.cmb_len)

        self.ed_style = QLineEdit(context.response_style if context else "")
        self.ed_style.setPlaceholderText("e.g. practical, direct")
        form.addRow("response style", self.ed_style)

        self.ed_params = QLineEdit(", ".join(
            f"{k}={v}" for k, v in (context.params if context else {}).items()))
        self.ed_params.setPlaceholderText(
            "key=value, key=value  (e.g. edition=Java Edition, version=1.21.x)")
        form.addRow("params", self.ed_params)

        buttons = QHBoxLayout()
        self.btn_ok = QPushButton("save")
        self.btn_ok.clicked.connect(self._on_ok)
        buttons.addWidget(self.btn_ok)
        self.btn_cancel = QPushButton("cancel")
        self.btn_cancel.setObjectName("flat")
        self.btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(self.btn_cancel)
        form.addRow(buttons)

    def _parse_params(self) -> dict:
        params: dict = {}
        for chunk in self.ed_params.text().split(","):
            if "=" not in chunk:
                continue
            key, _, value = chunk.partition("=")
            key = key.strip()
            value = value.strip()
            if not key or not value:
                continue
            if value.lower() in ("true", "false"):
                params[key] = value.lower() == "true"
            else:
                try:
                    params[key] = int(value)
                except ValueError:
                    params[key] = value
        return params

    def _on_ok(self) -> None:
        if not self.ed_name.text().strip():
            QMessageBox.warning(self, "Context", "name is required")
            return
        self.accept()

    def fields(self) -> dict:
        return {
            "name": self.ed_name.text().strip(),
            "description": self.ed_desc.text().strip(),
            "instructions": self.txt_instructions.toPlainText().strip(),
            "knowledge": self.txt_knowledge.toPlainText().strip(),
            "language": self.cmb_lang.currentText(),
            "response_length": self.cmb_len.currentText(),
            "response_style": self.ed_style.text().strip(),
            "params": self._parse_params(),
        }


class ContextManagerWidget(QWidget):
    """List + buttons + active-context combo."""

    active_changed = Signal()

    def __init__(self, contexts: ContextManager, parent=None):
        super().__init__(parent)
        self._contexts = contexts
        panel, col = section("ai contexts")

        row = QHBoxLayout()
        row.addWidget(QLabel("active context"))
        self.cmb_active = QComboBox()
        self.cmb_active.currentIndexChanged.connect(self._activate_current)
        row.addWidget(self.cmb_active, 1)
        col.addLayout(row)

        self.lst = QListWidget()
        self.lst.setFixedHeight(140)
        col.addWidget(self.lst)

        buttons = QHBoxLayout()
        self.btn_add = QPushButton("+ add context")
        self.btn_add.clicked.connect(self._add)
        buttons.addWidget(self.btn_add, 1)
        self.btn_edit = QPushButton("edit")
        self.btn_edit.setObjectName("flat")
        self.btn_edit.clicked.connect(self._edit)
        buttons.addWidget(self.btn_edit, 1)
        self.btn_delete = QPushButton("delete")
        self.btn_delete.setObjectName("danger")
        self.btn_delete.clicked.connect(self._delete)
        buttons.addWidget(self.btn_delete, 1)
        col.addLayout(buttons)

        buttons = QHBoxLayout()
        self.btn_activate = QPushButton("activate selected")
        self.btn_activate.setObjectName("flat")
        self.btn_activate.clicked.connect(self._activate_selected)
        buttons.addWidget(self.btn_activate, 1)
        self.btn_default = QPushButton("set as default")
        self.btn_default.setObjectName("flat")
        self.btn_default.clicked.connect(self._set_default)
        buttons.addWidget(self.btn_default, 1)
        col.addLayout(buttons)

        self.lbl_default = QLabel()
        self.lbl_default.setObjectName("subtitle")
        col.addWidget(self.lbl_default)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(panel)
        self.reload()

    def reload(self) -> None:
        self.cmb_active.blockSignals(True)
        self.cmb_active.clear()
        contexts = self._contexts.contexts
        for ctx in contexts:
            suffix = "  [default]" if ctx.id == self._contexts.default_id else ""
            self.cmb_active.addItem(ctx.name + suffix, ctx.id)
        idx = self.cmb_active.findData(self._contexts.active_id)
        if idx >= 0:
            self.cmb_active.setCurrentIndex(idx)
        self.cmb_active.blockSignals(False)

        self.lst.clear()
        for ctx in contexts:
            marker = "> " if ctx.id == self._contexts.active_id else "  "
            default = "  [default]" if ctx.id == self._contexts.default_id else ""
            self.lst.addItem(f"{marker}{ctx.name}{default} — {ctx.description[:60]}")
        default_ctx = self._contexts.get(self._contexts.default_id)
        self.lbl_default.setText(
            f"default context: {default_ctx.name if default_ctx else '-'}")

    def _selected_context(self) -> ContextConfig | None:
        row = self.lst.currentRow()
        contexts = self._contexts.contexts
        if 0 <= row < len(contexts):
            return contexts[row]
        return None

    def _add(self) -> None:
        dlg = ContextEditDialog(self)
        if dlg.exec() == QDialog.Accepted:
            fields = dlg.fields()
            try:
                self._contexts.create(fields.pop("name"), **fields)
                self._contexts.save()
                self.reload()
                self.active_changed.emit()
            except ValueError as exc:
                QMessageBox.warning(self, "Context", str(exc))

    def _edit(self) -> None:
        ctx = self._selected_context()
        if ctx is None:
            return
        dlg = ContextEditDialog(self, ctx)
        if dlg.exec() == QDialog.Accepted:
            fields = dlg.fields()
            try:
                self._contexts.update(ctx.id, **fields)
                self._contexts.save()
                self.reload()
                self.active_changed.emit()
            except ValueError as exc:
                QMessageBox.warning(self, "Context", str(exc))

    def _delete(self) -> None:
        ctx = self._selected_context()
        if ctx is None:
            return
        if len(self._contexts.contexts) <= 1:
            QMessageBox.information(self, "Context", "at least one context must remain")
            return
        btn = QMessageBox.question(
            self, "Delete context",
            f"Delete '{ctx.name}'? Its conversation history is also removed.")
        if btn != QMessageBox.Yes:
            return
        self._contexts.delete(ctx.id)
        self._contexts.save()
        self.reload()
        self.active_changed.emit()

    def _activate_current(self) -> None:
        ctx_id = self.cmb_active.currentData()
        if ctx_id and self._contexts.set_active(ctx_id):
            self._contexts.save()
            self.reload()
            self.active_changed.emit()

    def _activate_selected(self) -> None:
        ctx = self._selected_context()
        if ctx is not None and self._contexts.set_active(ctx.id):
            self._contexts.save()
            self.reload()
            self.active_changed.emit()

    def _set_default(self) -> None:
        ctx = self._selected_context()
        if ctx is not None and self._contexts.set_default(ctx.id):
            self._contexts.save()
            self.reload()
