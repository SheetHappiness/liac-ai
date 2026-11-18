from typing import Protocol

from vtuber.contracts.events import RuntimeOutput


class OutputSink(Protocol):
    def __call__(self, output: RuntimeOutput, /) -> None:
        """Consume a notification promptly; never change domain state here."""
        ...
