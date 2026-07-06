"""Generic command / undo-redo framework.

Every mutation of a Document goes through a Command so that the GUI, the
programmatic API and the MCP server all share one undo history — a major
upgrade over the original, where only three tools were undoable and redo
was never implemented.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any


class Command(ABC):
    """A reversible document mutation."""

    #: human-readable label shown in Edit menu ("Undo Move points")
    label: str = "Edit"

    @abstractmethod
    def do(self) -> Any: ...

    @abstractmethod
    def undo(self) -> None: ...

    def redo(self) -> Any:
        return self.do()

    def merge_with(self, other: Command) -> bool:
        """Try to absorb *other* (a newer command) into self.

        Used to coalesce e.g. successive point drags. Return True if merged.
        """
        return False


class FunctionCommand(Command):
    """Command built from do/undo callables — convenient for simple mutations."""

    def __init__(self, label: str, do: Callable[[], Any], undo: Callable[[], None]):
        self.label = label
        self._do = do
        self._undo = undo

    def do(self) -> Any:
        return self._do()

    def undo(self) -> None:
        self._undo()


class CompositeCommand(Command):
    """Several commands applied as one undo step."""

    def __init__(self, label: str, commands: list[Command] | None = None):
        self.label = label
        self.commands: list[Command] = list(commands or [])

    def add(self, cmd: Command) -> None:
        self.commands.append(cmd)

    def do(self) -> Any:
        result = None
        for c in self.commands:
            result = c.do()
        return result

    def undo(self) -> None:
        for c in reversed(self.commands):
            c.undo()


class CommandStack:
    """Undo/redo stack with optional merging and change notification."""

    def __init__(self, limit: int = 1000):
        self._undo: list[Command] = []
        self._redo: list[Command] = []
        self._limit = limit
        #: called after any do/undo/redo; GUI hooks repaint here
        self.on_change: list[Callable[[], None]] = []
        self._transaction: CompositeCommand | None = None

    # -- transactions ------------------------------------------------
    def begin(self, label: str) -> None:
        """Group subsequent pushes into one undo step until commit()."""
        if self._transaction is None:
            self._transaction = CompositeCommand(label)

    def commit(self) -> None:
        txn, self._transaction = self._transaction, None
        if txn and txn.commands:
            self._push(txn)
            self._notify()

    # -- core API ----------------------------------------------------
    def push(self, cmd: Command, merge: bool = False) -> Any:
        """Execute *cmd* and record it for undo."""
        result = cmd.do()
        if self._transaction is not None:
            self._transaction.add(cmd)
            return result
        if merge and self._undo and self._undo[-1].merge_with(cmd):
            pass
        else:
            self._push(cmd)
        self._notify()
        return result

    def _push(self, cmd: Command) -> None:
        self._undo.append(cmd)
        if len(self._undo) > self._limit:
            del self._undo[0]
        self._redo.clear()

    def undo(self) -> str | None:
        if not self._undo:
            return None
        cmd = self._undo.pop()
        cmd.undo()
        self._redo.append(cmd)
        self._notify()
        return cmd.label

    def redo(self) -> str | None:
        if not self._redo:
            return None
        cmd = self._redo.pop()
        cmd.redo()
        self._undo.append(cmd)
        self._notify()
        return cmd.label

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_label(self) -> str | None:
        return self._undo[-1].label if self._undo else None

    @property
    def redo_label(self) -> str | None:
        return self._redo[-1].label if self._redo else None

    @property
    def depth(self) -> int:
        return len(self._undo)

    def clear(self) -> None:
        self._undo.clear()
        self._redo.clear()
        self._notify()

    def _notify(self) -> None:
        for cb in self.on_change:
            cb()
