"""Convenience façade for Virtuoso access.

* ``VirtuosoClient`` – class for ad‑hoc connections
* ``virtuoso``       – shared singleton injected by ``config.py``

Typing note
-----------
Python 3.9 does **not** support the ``A | B`` union operator, so the
public ``virtuoso`` attribute is annotated via ``typing.Union`` only when
`TYPE_CHECKING` is *on*.  At runtime we simply overwrite the placeholder
instance.
"""

from typing import TYPE_CHECKING, Union

from .virtuoso_client import VirtuosoClient


class _NotInitialised:
    """Placeholder that errors on any attribute access."""

    def __getattr__(self, item):  # pragma: no cover
        raise RuntimeError(
            "store.virtuoso accessed before src.config created the singleton"
        )

    def __repr__(self):  # pragma: no cover
        return "<virtuoso :: not initialised>"


# ── public singleton placeholder ─────────────────────────────────────────
if TYPE_CHECKING:
    virtuoso: Union[VirtuosoClient, _NotInitialised]
else:
    virtuoso = _NotInitialised()  # type: ignore[assignment]


__all__ = ["VirtuosoClient", "virtuoso"]
