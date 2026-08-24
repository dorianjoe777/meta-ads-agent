#!/usr/bin/env python3
"""Trusted authorization for choosing a Meta ad account and Page.

The language model may suggest when a workspace choice is needed, but it must
not be the authority that chooses the assets.  This module turns a trusted raw
inbound message into a short-lived, one-use ticket that is bound to:

* the Telegram chat and Hermes session;
* the exact ordered Meta inventory shown to the buyer;
* the active account/Page pair before the change;
* the intended account/Page pair after the change; and
* the inbound message sequence and a hash of its evidence.

Only public asset identifiers and names are persisted.  OAuth/user/Page tokens
and other credential fields are deliberately discarded at the boundary.
"""

from __future__ import annotations

import contextlib
import difflib
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

try:  # Linux production runtime.  The fallback still protects one process.
    import fcntl
except ImportError:  # pragma: no cover - Windows is not the deployed runtime.
    fcntl = None


STATE_VERSION = 1
DEFAULT_TTL_SECONDS = 1800
MIN_TTL_SECONDS = 30
MAX_TTL_SECONDS = 1800
MAX_MESSAGE_LENGTH = 4_000
MAX_ASSETS_PER_KIND = 2_000

_ACCOUNT_SCOPE_WORDS = {
    "account",
    "accounts",
    "adaccount",
    "cuenta",
    "cuentas",
    "publicitaria",
    "publicitarias",
    # Common transpositions/omissions accepted without making arbitrary words
    # into security-sensitive entity scopes.
    "acount",
    "accoutn",
    "accont",
    "ceunta",
    "cuetna",
    "cueta",
    "cunta",
}
_PAGE_SCOPE_WORDS = {
    "facebookpage",
    "page",
    "pages",
    "pagina",
    "paginas",
    "paguina",
    "pagian",
    "paina",
    "pgae",
}
_SCOPE_FALSE_FRIENDS = {
    "cuento",
    "cuentos",
    "cuanto",
    "cuantos",
    "cuanta",
    "cuantas",
}
_NUMBER_WORDS = {
    "uno": 1,
    "una": 1,
    "un": 1,
    "primera": 1,
    "primer": 1,
    "primero": 1,
    "one": 1,
    "first": 1,
    "dos": 2,
    "segunda": 2,
    "segundo": 2,
    "two": 2,
    "second": 2,
    "tres": 3,
    "tercera": 3,
    "tercer": 3,
    "tercero": 3,
    "three": 3,
    "third": 3,
    "cuatro": 4,
    "cuarta": 4,
    "cuarto": 4,
    "four": 4,
    "fourth": 4,
    "cinco": 5,
    "quinta": 5,
    "quinto": 5,
    "five": 5,
    "fifth": 5,
    "seis": 6,
    "sexta": 6,
    "sexto": 6,
    "six": 6,
    "sixth": 6,
    "siete": 7,
    "septima": 7,
    "septimo": 7,
    "seven": 7,
    "seventh": 7,
    "ocho": 8,
    "octava": 8,
    "octavo": 8,
    "eight": 8,
    "eighth": 8,
    "nueve": 9,
    "novena": 9,
    "noveno": 9,
    "nine": 9,
    "ninth": 9,
    "diez": 10,
    "decima": 10,
    "decimo": 10,
    "ten": 10,
    "tenth": 10,
}
_GENERIC_DELEGATIONS = (
    "usa lo que veas",
    "usa la que veas",
    "usa el que veas",
    "usa cualquiera",
    "cualquiera esta bien",
    "elige tu",
    "escoge tu",
    "lo que sea",
    "la que sea",
    "whatever",
    "any one",
    "you choose",
)


class SelectionAuthorizationError(ValueError):
    """Base class for a rejected selection authorization operation."""


class SelectionIntentNotFound(SelectionAuthorizationError):
    """The selection intent is missing, expired, or already consumed."""


class SelectionBindingMismatch(SelectionAuthorizationError):
    """Trusted runtime context does not match the selection intent/ticket."""


class SelectionTicketInvalid(SelectionAuthorizationError):
    """The selection ticket is unknown, malformed, expired, or already used."""


def _text(value: Any, *, maximum: int = 512) -> str:
    value = str(value or "").strip()
    if len(value) > maximum:
        raise SelectionAuthorizationError(f"value exceeds {maximum} characters")
    return value


def normalize_selection_text(value: Any) -> str:
    """Accent-insensitive normalization used only for entity resolution."""

    value = _text(value, maximum=MAX_MESSAGE_LENGTH)
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[a-z0-9]+", without_marks))


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _message_hash(raw_message: str, message_sequence: int) -> str:
    payload = {
        "sequence": int(message_sequence),
        "text": normalize_selection_text(raw_message),
    }
    return _sha256(_canonical_json(payload))


def _asset_kind_inventory(inventory: Mapping[str, Any], kind: str) -> list[dict[str, Any]]:
    source_key = "accounts" if kind == "account" else "pages"
    raw_assets = inventory.get(source_key, [])
    if not isinstance(raw_assets, list):
        raise SelectionAuthorizationError(f"inventory.{source_key} must be a list")
    if len(raw_assets) > MAX_ASSETS_PER_KIND:
        raise SelectionAuthorizationError(f"inventory.{source_key} is too large")

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_assets:
        if not isinstance(raw, Mapping):
            raise SelectionAuthorizationError(f"inventory.{source_key} contains an invalid asset")
        asset_id = _text(raw.get("id"), maximum=256)
        if not asset_id:
            raise SelectionAuthorizationError(f"inventory.{source_key} asset id is required")
        if asset_id in seen:
            raise SelectionAuthorizationError(f"inventory.{source_key} contains duplicate id {asset_id}")
        seen.add(asset_id)
        # A discovered Page without publishing capability cannot become active.
        if kind == "page" and raw.get("can_publish") is False:
            continue
        result.append(
            {
                "id": asset_id,
                "name": _text(raw.get("name") or asset_id, maximum=512),
                "kind": kind,
                "ordinal": len(result) + 1,
            }
        )
    return result


def sanitize_inventory(inventory: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Return only selectable public metadata; credential fields never cross in."""

    if not isinstance(inventory, Mapping):
        raise SelectionAuthorizationError("inventory must be an object")
    return {
        "accounts": _asset_kind_inventory(inventory, "account"),
        "pages": _asset_kind_inventory(inventory, "page"),
    }


def inventory_fingerprint(inventory: Mapping[str, Any]) -> str:
    """Hash the exact selectable asset order shown to the buyer."""

    safe = sanitize_inventory(inventory)
    compact = {
        "accounts": [{"id": item["id"], "name": item["name"]} for item in safe["accounts"]],
        "pages": [{"id": item["id"], "name": item["name"]} for item in safe["pages"]],
    }
    return _sha256(_canonical_json(compact))


def _normalize_pair(current_pair: Mapping[str, Any] | None) -> dict[str, str]:
    pair = current_pair if isinstance(current_pair, Mapping) else {}
    return {
        "ad_account_id": _text(pair.get("ad_account_id") or pair.get("account_id"), maximum=256),
        "page_id": _text(pair.get("page_id"), maximum=256),
    }


def _scope_token(token: str, words: set[str]) -> bool:
    if token in words:
        return True
    if token in _SCOPE_FALSE_FRIENDS:
        return False
    if len(token) < 4:
        return False
    return max(difflib.SequenceMatcher(None, token, word).ratio() for word in words) >= 0.78


def _scope_positions(tokens: Sequence[str], kind: str) -> list[int]:
    words = _ACCOUNT_SCOPE_WORDS if kind == "account" else _PAGE_SCOPE_WORDS
    positions = [index for index, token in enumerate(tokens) if _scope_token(token, words)]
    # "Facebook page" and "ad account" normalize into two tokens.  Either the
    # specific noun above or these adjacent pairs provide the same scope.
    if kind == "page":
        positions.extend(index + 1 for index in range(len(tokens) - 1) if tokens[index:index + 2] == ["facebook", "page"])
    else:
        positions.extend(index + 1 for index in range(len(tokens) - 1) if tokens[index:index + 2] == ["ad", "account"])
    return sorted(set(positions))


def _number_value(token: str) -> int | None:
    if token.isdigit():
        value = int(token)
        return value if 1 <= value <= MAX_ASSETS_PER_KIND else None
    match = re.fullmatch(r"(\d+)(?:st|nd|rd|th|a|o)?", token)
    if match:
        value = int(match.group(1))
        return value if 1 <= value <= MAX_ASSETS_PER_KIND else None
    return _NUMBER_WORDS.get(token)


def _ordinal_candidates(
    tokens: Sequence[str],
    scope_positions: Sequence[int],
    other_scope_positions: Sequence[int],
) -> set[int]:
    result: set[int] = set()
    for scope_index in scope_positions:
        earlier_other = max(
            (position for position in other_scope_positions if position < scope_index),
            default=-1,
        )
        later_other = min(
            (position for position in other_scope_positions if position > scope_index),
            default=len(tokens),
        )

        # Prefer a number after the noun ("cuenta 2").  This avoids assigning
        # the same number to the following noun in "cuenta 2, página 1".
        after: int | None = None
        for index in range(scope_index + 1, min(len(tokens), scope_index + 4, later_other)):
            value = _number_value(tokens[index])
            if value is not None:
                after = value
                break
        if after is not None:
            result.add(after)
            continue

        # Also accept natural ordinals before the noun ("segunda cuenta"), but
        # never steal a number that is closer to an earlier opposite-kind noun.
        for index in range(scope_index - 1, max(-1, scope_index - 4, earlier_other), -1):
            value = _number_value(tokens[index])
            if value is None:
                continue
            distance_here = scope_index - index
            distance_other = index - earlier_other if earlier_other >= 0 else MAX_ASSETS_PER_KIND
            if earlier_other >= 0 and distance_other <= distance_here:
                break
            result.add(value)
            break
    return result


def _id_in_message(asset_id: str, normalized_message: str) -> bool:
    normalized_id = normalize_selection_text(asset_id)
    if not normalized_id:
        return False
    id_tokens = normalized_id.split()
    message_tokens = normalized_message.split()
    compact_id = "".join(id_tokens)
    # Numeric Page IDs must be long enough to avoid treating an ordinal or
    # budget as an asset identifier.
    if compact_id.isdigit() and len(compact_id) < 6:
        return False
    if compact_id.isdigit():
        return compact_id in message_tokens
    size = len(id_tokens)
    return any(message_tokens[index:index + size] == id_tokens for index in range(len(message_tokens) - size + 1))


def _name_score(name: str, message_tokens: Sequence[str]) -> float:
    name_norm = normalize_selection_text(name)
    if not name_norm:
        return 0.0
    message_norm = " ".join(message_tokens)
    if name_norm in message_norm:
        return 1.0
    name_tokens = name_norm.split()
    if not name_tokens:
        return 0.0
    # Single very short/generic names are exact-only; fuzzy matching them would
    # authorize common conversational words such as "one" or "new".
    if len(name_tokens) == 1 and len(name_tokens[0]) < 6:
        return 0.0
    best = 0.0
    # Buyers naturally shorten a displayed name (“Rodeo” for
    # “Rodeo - Car Detailing”). A distinctive exact token is useful evidence;
    # duplicate prefixes remain ambiguous because every matching asset gets
    # the same score and the resolver refuses close ties.
    shared = {
        token for token in name_tokens
        if len(token) >= 5 and token in set(message_tokens)
    }
    if shared:
        best = max(best, min(0.94, 0.82 + 0.04 * (len(shared) - 1)))
    minimum = max(1, len(name_tokens) - 1)
    maximum = min(len(message_tokens), len(name_tokens) + 1)
    for size in range(minimum, maximum + 1):
        for start in range(0, len(message_tokens) - size + 1):
            phrase = " ".join(message_tokens[start:start + size])
            best = max(best, difflib.SequenceMatcher(None, name_norm, phrase).ratio())
    return best


def _tokens_in_kind_scope(
    tokens: Sequence[str],
    scope_positions: Sequence[int],
    other_scope_positions: Sequence[int],
) -> list[str]:
    """Return tokens whose nearest entity noun belongs to this asset kind.

    This is deliberately symmetric: both “cuenta Acme” and “Acme como cuenta”
    bind Acme to the account scope. It also prevents that name from matching a
    Page with the same name elsewhere in the inventory.
    """
    if not scope_positions or not other_scope_positions:
        return list(tokens)
    selected: list[str] = []
    for index, token in enumerate(tokens):
        own_distance = min(abs(index - position) for position in scope_positions)
        other_distance = min(abs(index - position) for position in other_scope_positions)
        tie_belongs_here = False
        if own_distance == other_distance:
            nearest_own = min(scope_positions, key=lambda position: abs(index - position))
            nearest_other = min(other_scope_positions, key=lambda position: abs(index - position))
            # At an exact midpoint, natural “Name como cuenta/página” grammar
            # belongs to the upcoming noun on the right.
            tie_belongs_here = nearest_own > nearest_other or index in scope_positions
        if own_distance < other_distance or tie_belongs_here:
            selected.append(token)
    return selected or list(tokens)


def _resolve_kind(
    safe_inventory: Mapping[str, list[dict[str, Any]]],
    kind: str,
    normalized_message: str,
) -> dict[str, Any]:
    key = "accounts" if kind == "account" else "pages"
    assets = safe_inventory[key]
    tokens = normalized_message.split()
    scope_positions = _scope_positions(tokens, kind)
    other_kind = "page" if kind == "account" else "account"
    other_scope_positions = _scope_positions(tokens, other_kind)
    scoped = bool(scope_positions)
    kind_tokens = _tokens_in_kind_scope(tokens, scope_positions, other_scope_positions)
    kind_message = " ".join(kind_tokens)

    id_matches = [asset for asset in assets if _id_in_message(asset["id"], kind_message)]
    if len(id_matches) > 1:
        return {"status": "ambiguous", "kind": kind, "candidate_ids": [item["id"] for item in id_matches], "scoped": scoped}
    if len(id_matches) == 1:
        return {"status": "resolved", "asset": id_matches[0], "evidence": "id", "scoped": scoped}

    ordinals = _ordinal_candidates(tokens, scope_positions, other_scope_positions)
    ordinal_matches = [assets[value - 1] for value in ordinals if 1 <= value <= len(assets)]
    unique_ordinal_matches = {item["id"]: item for item in ordinal_matches}
    if len(unique_ordinal_matches) > 1:
        return {"status": "ambiguous", "kind": kind, "candidate_ids": list(unique_ordinal_matches), "scoped": scoped}
    if len(unique_ordinal_matches) == 1:
        asset = next(iter(unique_ordinal_matches.values()))
        return {"status": "resolved", "asset": asset, "evidence": "ordinal", "scoped": True}

    exact_name_matches: list[tuple[tuple[int, int], dict[str, Any]]] = []
    for asset in assets:
        name_norm = normalize_selection_text(asset["name"])
        if len(name_norm) >= 3 and name_norm in kind_message:
            exact_name_matches.append(((len(name_norm.split()), len(name_norm)), asset))
    # Prefer the most specific complete name. “Dorian Singularity” must beat
    # accounts named only “Dorian”; duplicate equally-specific names remain
    # ambiguous and still require an ordinal or ID.
    exact_names: list[dict[str, Any]] = []
    if exact_name_matches:
        best_specificity = max(item[0] for item in exact_name_matches)
        exact_names = [asset for specificity, asset in exact_name_matches if specificity == best_specificity]
    if len(exact_names) > 1:
        return {"status": "ambiguous", "kind": kind, "candidate_ids": [item["id"] for item in exact_names], "scoped": scoped}
    if len(exact_names) == 1:
        return {"status": "resolved", "asset": exact_names[0], "evidence": "name", "scoped": scoped}

    scored = sorted(
        ((_name_score(asset["name"], kind_tokens), asset) for asset in assets),
        key=lambda item: item[0],
        reverse=True,
    )
    if not scored or scored[0][0] < 0.80:
        return {"status": "none", "kind": kind, "scoped": scoped}
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    if scored[0][0] - second_score < 0.08:
        candidates = [asset["id"] for score, asset in scored if scored[0][0] - score < 0.08]
        return {"status": "ambiguous", "kind": kind, "candidate_ids": candidates, "scoped": scoped}
    return {"status": "resolved", "asset": scored[0][1], "evidence": "fuzzy_name", "scoped": scoped, "score": round(scored[0][0], 3)}


def resolve_selection_message(raw_message: str, inventory: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve explicit buyer evidence without trusting model-supplied IDs."""

    raw = unicodedata.normalize("NFKC", str(raw_message or "")).strip()
    if not raw:
        return {"status": "rejected", "reason": "empty_message"}
    safe = sanitize_inventory(inventory)

    # Canonical compact reply shown by Admira: first Page, then ad account.
    # This is evaluated only while a trusted selection intent is active, so a
    # bare “1, 8” elsewhere in conversation can never mutate the workspace.
    compact_pair = re.fullmatch(r"([0-9]+)(?:\s*,\s*|\s+)([0-9]+)", raw)
    if compact_pair:
        page_ordinal = int(compact_pair.group(1))
        account_ordinal = int(compact_pair.group(2))
        if (
            page_ordinal is not None
            and account_ordinal is not None
            and 1 <= page_ordinal <= len(safe["pages"])
            and 1 <= account_ordinal <= len(safe["accounts"])
        ):
            return {
                "status": "resolved",
                "account": {
                    "status": "resolved",
                    "asset": safe["accounts"][account_ordinal - 1],
                    "evidence": "canonical_numeric_pair",
                    "scoped": True,
                },
                "page": {
                    "status": "resolved",
                    "asset": safe["pages"][page_ordinal - 1],
                    "evidence": "canonical_numeric_pair",
                    "scoped": True,
                },
            }
        return {"status": "rejected", "reason": "numeric_pair_out_of_range"}
    return {"status": "rejected", "reason": "numeric_pair_required"}

class MetaSelectionAuthorizer:
    """Persistent selection-intent and one-use ticket manager."""

    def __init__(
        self,
        state_path: str | Path,
        *,
        key_path: str | Path | None = None,
        signing_key: bytes | None = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.state_path = Path(state_path)
        self.key_path = Path(key_path) if key_path else self.state_path.with_suffix(self.state_path.suffix + ".key")
        self.lock_path = self.state_path.with_suffix(self.state_path.suffix + ".lock")
        self.ttl_seconds = int(ttl_seconds)
        if not MIN_TTL_SECONDS <= self.ttl_seconds <= MAX_TTL_SECONDS:
            raise SelectionAuthorizationError(
                f"ttl_seconds must be between {MIN_TTL_SECONDS} and {MAX_TTL_SECONDS}"
            )
        self._clock = clock or time.time
        self._thread_lock = threading.RLock()
        self._provided_key = bytes(signing_key) if signing_key else None
        if self._provided_key is not None and len(self._provided_key) < 32:
            raise SelectionAuthorizationError("signing_key must contain at least 32 bytes")

    def _now(self) -> int:
        return int(self._clock())

    def _ensure_parent(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _signing_key(self) -> bytes:
        if self._provided_key is not None:
            return self._provided_key
        self._ensure_parent()
        try:
            fd = os.open(self.key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            try:
                os.write(fd, secrets.token_bytes(32))
            finally:
                os.close(fd)
        try:
            key = self.key_path.read_bytes()
        except OSError as exc:
            raise SelectionAuthorizationError("selection signing key is unavailable") from exc
        if len(key) < 32:
            raise SelectionAuthorizationError("selection signing key is invalid")
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return key

    def _ticket_digest(self, ticket: str) -> str:
        return hmac.new(self._signing_key(), ticket.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _empty_state() -> dict[str, Any]:
        return {"version": STATE_VERSION, "intents": {}, "tickets": {}, "used_tickets": {}}

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return self._empty_state()
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SelectionAuthorizationError("selection authorization state is unreadable") from exc
        if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
            raise SelectionAuthorizationError("selection authorization state has an unsupported version")
        for key in ("intents", "tickets", "used_tickets"):
            if not isinstance(state.get(key), dict):
                raise SelectionAuthorizationError("selection authorization state is invalid")
        return state

    def _write_state(self, state: Mapping[str, Any]) -> None:
        self._ensure_parent()
        fd, temporary = tempfile.mkstemp(prefix=f".{self.state_path.name}.", dir=str(self.state_path.parent))
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)
            os.chmod(self.state_path, 0o600)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    @contextlib.contextmanager
    def _state(self) -> Iterator[dict[str, Any]]:
        self._ensure_parent()
        with self._thread_lock:
            with self.lock_path.open("a+", encoding="utf-8") as lock_handle:
                try:
                    os.chmod(self.lock_path, 0o600)
                except OSError:
                    pass
                if fcntl is not None:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                state = self._load_state()
                self._purge_expired(state)
                try:
                    yield state
                finally:
                    self._write_state(state)
                    if fcntl is not None:
                        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _purge_expired(self, state: dict[str, Any]) -> None:
        now = self._now()
        state["intents"] = {
            key: value for key, value in state["intents"].items()
            if int(value.get("expires_at", 0)) > now
        }
        state["tickets"] = {
            key: value for key, value in state["tickets"].items()
            if int(value.get("expires_at", 0)) > now
        }
        state["used_tickets"] = {
            key: value for key, value in state["used_tickets"].items()
            if int(value.get("expires_at", 0)) > now
        }

    @staticmethod
    def _require_runtime_binding(chat_id: Any, session_id: Any, message_sequence: Any | None = None) -> tuple[str, str, int | None]:
        chat = _text(chat_id, maximum=256)
        session = _text(session_id, maximum=256)
        if not chat or not session:
            raise SelectionBindingMismatch("chat_id and session_id are required")
        sequence: int | None = None
        if message_sequence is not None:
            if isinstance(message_sequence, bool):
                raise SelectionBindingMismatch("message_sequence must be an integer")
            try:
                sequence = int(message_sequence)
            except (TypeError, ValueError) as exc:
                raise SelectionBindingMismatch("message_sequence must be an integer") from exc
            if sequence < 0:
                raise SelectionBindingMismatch("message_sequence must be non-negative")
        return chat, session, sequence

    def open_intent(
        self,
        *,
        chat_id: Any,
        session_id: Any,
        inventory: Mapping[str, Any],
        current_pair: Mapping[str, Any] | None,
        opened_after_sequence: int,
        mode: str = "auto",
    ) -> dict[str, Any]:
        """Open a short-lived intent before asking the buyer to choose assets."""

        chat, session, sequence = self._require_runtime_binding(chat_id, session_id, opened_after_sequence)
        assert sequence is not None
        safe = sanitize_inventory(inventory)
        if not safe["accounts"] or not safe["pages"]:
            raise SelectionAuthorizationError("at least one selectable account and Page are required")
        pair = _normalize_pair(current_pair)
        account_ids = {item["id"] for item in safe["accounts"]}
        page_ids = {item["id"] for item in safe["pages"]}
        if pair["ad_account_id"] and pair["ad_account_id"] not in account_ids:
            raise SelectionAuthorizationError("current ad account is not present in inventory")
        if pair["page_id"] and pair["page_id"] not in page_ids:
            raise SelectionAuthorizationError("current Page is not present in inventory")
        if mode == "auto":
            mode = "switch" if pair["ad_account_id"] or pair["page_id"] else "initial"
        if mode not in {"initial", "switch"}:
            raise SelectionAuthorizationError("mode must be initial, switch, or auto")

        intent_id = secrets.token_urlsafe(24)
        now = self._now()
        intent = {
            "chat_id": chat,
            "session_id": session,
            "mode": mode,
            "inventory": safe,
            "inventory_hash": inventory_fingerprint(safe),
            "current_pair": pair,
            "opened_after_sequence": sequence,
            "last_message_sequence": sequence,
            "created_at": now,
            "expires_at": now + self.ttl_seconds,
        }
        with self._state() as state:
            # Only one current intent per chat/session.  Superseding the older
            # prompt prevents a delayed Telegram reply selecting stale assets.
            state["intents"] = {
                key: value for key, value in state["intents"].items()
                if not (value.get("chat_id") == chat and value.get("session_id") == session)
            }
            state["tickets"] = {
                key: value for key, value in state["tickets"].items()
                if not (value.get("chat_id") == chat and value.get("session_id") == session)
            }
            state["intents"][intent_id] = intent
        return {
            "intent_id": intent_id,
            "mode": mode,
            "inventory_hash": intent["inventory_hash"],
            "expires_at": intent["expires_at"],
            "accounts": [{"id": item["id"], "name": item["name"], "ordinal": item["ordinal"]} for item in safe["accounts"]],
            "pages": [{"id": item["id"], "name": item["name"], "ordinal": item["ordinal"]} for item in safe["pages"]],
        }

    def authorize_message(
        self,
        *,
        intent_id: str,
        chat_id: Any,
        session_id: Any,
        message_sequence: int,
        raw_message: str,
        inventory: Mapping[str, Any],
        current_pair: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Resolve trusted inbound text and issue a one-use exact-pair ticket."""

        intent_id = _text(intent_id, maximum=256)
        chat, session, sequence = self._require_runtime_binding(chat_id, session_id, message_sequence)
        assert sequence is not None
        safe_now = sanitize_inventory(inventory)
        inventory_hash = inventory_fingerprint(safe_now)
        pair_now = _normalize_pair(current_pair)
        raw_message = _text(raw_message, maximum=MAX_MESSAGE_LENGTH)

        with self._state() as state:
            intent = state["intents"].get(intent_id)
            if not intent:
                raise SelectionIntentNotFound("selection intent is missing or expired")
            if intent["chat_id"] != chat or intent["session_id"] != session:
                raise SelectionBindingMismatch("selection intent belongs to another chat or session")
            if inventory_hash != intent["inventory_hash"]:
                raise SelectionBindingMismatch("Meta inventory changed after the selection prompt")
            if pair_now != intent["current_pair"]:
                raise SelectionBindingMismatch("active Meta workspace changed after the selection prompt")
            if sequence <= int(intent["last_message_sequence"]):
                raise SelectionBindingMismatch("inbound message is stale or already processed")

            resolution = resolve_selection_message(raw_message, intent["inventory"])
            intent["last_message_sequence"] = sequence
            if resolution["status"] != "resolved":
                return {
                    "status": resolution["status"],
                    "reason": resolution["reason"],
                    "intent_id": intent_id,
                    "expires_at": intent["expires_at"],
                }

            account_result = resolution["account"]
            page_result = resolution["page"]
            account_id = account_result["asset"]["id"] if account_result["status"] == "resolved" else ""
            page_id = page_result["asset"]["id"] if page_result["status"] == "resolved" else ""
            message_hash = _message_hash(raw_message, sequence)
            if not account_id or not page_id:
                raise SelectionAuthorizationError("strict numeric resolution did not produce a complete pair")

            target = {"ad_account_id": account_id, "page_id": page_id}
            if intent["mode"] == "switch" and target == intent["current_pair"]:
                del state["intents"][intent_id]
                return {"status": "unchanged", "selected": target}

            token = secrets.token_urlsafe(32)
            digest = self._ticket_digest(token)
            ticket_record = {
                "chat_id": chat,
                "session_id": session,
                "mode": intent["mode"],
                "inventory_hash": intent["inventory_hash"],
                "old_pair": intent["current_pair"],
                "new_pair": target,
                "message_sequence": sequence,
                "message_hash": message_hash,
                "created_at": self._now(),
                "expires_at": min(intent["expires_at"], self._now() + self.ttl_seconds),
            }
            state["tickets"][digest] = ticket_record
            del state["intents"][intent_id]
            return {
                "status": "authorized",
                "ticket": token,
                "selection": target,
                "old_selection": ticket_record["old_pair"],
                "inventory_hash": ticket_record["inventory_hash"],
                "message_hash": ticket_record["message_hash"],
                "message_sequence": sequence,
                "expires_at": ticket_record["expires_at"],
            }

    def current_intent(self, *, chat_id: Any, session_id: Any) -> dict[str, Any] | None:
        """Return a compact view of the one active intent for this runtime scope."""

        chat, session, _ = self._require_runtime_binding(chat_id, session_id)
        with self._state() as state:
            matches = [
                (intent_id, intent)
                for intent_id, intent in state["intents"].items()
                if intent.get("chat_id") == chat and intent.get("session_id") == session
            ]
            if not matches:
                return None
            if len(matches) != 1:  # Defensive against an older/corrupt writer.
                raise SelectionAuthorizationError("multiple active selection intents exist")
            intent_id, intent = matches[0]
            return {
                "intent_id": intent_id,
                "mode": intent["mode"],
                "inventory_hash": intent["inventory_hash"],
                "current_pair": dict(intent["current_pair"]),
                "opened_after_sequence": intent["opened_after_sequence"],
                "expires_at": intent["expires_at"],
            }

    def authorize_current_message(
        self,
        *,
        chat_id: Any,
        session_id: Any,
        message_sequence: int,
        raw_message: str,
        inventory: Mapping[str, Any],
        current_pair: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Authorize against the sole active intent without exposing its ID."""

        current = self.current_intent(chat_id=chat_id, session_id=session_id)
        if not current:
            raise SelectionIntentNotFound("selection intent is missing or expired")
        return self.authorize_message(
            intent_id=current["intent_id"],
            chat_id=chat_id,
            session_id=session_id,
            message_sequence=message_sequence,
            raw_message=raw_message,
            inventory=inventory,
            current_pair=current_pair,
        )

    def consume_ticket(
        self,
        *,
        ticket: str,
        chat_id: Any,
        session_id: Any,
        inventory: Mapping[str, Any],
        current_pair: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Consume a ticket for callers whose work completes inside this call.

        Workspace persistence needs a wider transaction: the ticket must stay
        retryable until every dependent file has been written and verified.
        Those callers use :meth:`ticket_transaction` instead.  Keeping this
        convenience method preserves the one-shot API for simpler consumers.
        """

        with self.ticket_transaction(
            ticket=ticket,
            chat_id=chat_id,
            session_id=session_id,
            inventory=inventory,
            current_pair=current_pair,
        ) as authorized:
            return authorized

    @contextlib.contextmanager
    def ticket_transaction(
        self,
        *,
        ticket: str,
        chat_id: Any,
        session_id: Any,
        inventory: Mapping[str, Any],
        current_pair: Mapping[str, Any] | None,
    ) -> Iterator[dict[str, Any]]:
        """Reserve a ticket and consume it only after the caller succeeds.

        The authorizer's process-wide file lock remains held while the caller
        performs its durable operation.  If that operation raises, the ticket
        remains in ``tickets`` and can be retried.  A normal context exit moves
        it to ``used_tickets`` exactly once, preventing a second process from
        persisting a competing workspace selection.
        """

        ticket = _text(ticket, maximum=512)
        if not ticket:
            raise SelectionTicketInvalid("selection ticket is required")
        chat, session, _ = self._require_runtime_binding(chat_id, session_id)
        inventory_hash = inventory_fingerprint(inventory)
        pair = _normalize_pair(current_pair)
        digest = self._ticket_digest(ticket)

        with self._state() as state:
            if digest in state["used_tickets"]:
                raise SelectionTicketInvalid("selection ticket was already consumed")
            record = state["tickets"].get(digest)
            if not record:
                raise SelectionTicketInvalid("selection ticket is invalid or expired")
            if record["chat_id"] != chat or record["session_id"] != session:
                raise SelectionBindingMismatch("selection ticket belongs to another chat or session")
            if record["inventory_hash"] != inventory_hash:
                raise SelectionBindingMismatch("Meta inventory changed before selection")
            if record["old_pair"] != pair:
                raise SelectionBindingMismatch("active Meta workspace changed before selection")

            authorized = {
                "authorized": True,
                "mode": record["mode"],
                "old_selection": record["old_pair"],
                "selection": record["new_pair"],
                "inventory_hash": record["inventory_hash"],
                "message_hash": record["message_hash"],
                "message_sequence": record["message_sequence"],
                "expires_at": record["expires_at"],
            }
            try:
                yield authorized
            except BaseException:
                # _state writes the unchanged state on exit, so a failed
                # downstream persistence attempt keeps this exact ticket
                # available for a bounded retry.
                raise
            else:
                # The exclusive lock held by _state guarantees the record is
                # still ours.  Move it only after the caller's work succeeded.
                del state["tickets"][digest]
                state["used_tickets"][digest] = {
                    "chat_id": chat,
                    "session_id": session,
                    "expires_at": record["expires_at"],
                }

    def clear(self, *, chat_id: Any | None = None, session_id: Any | None = None) -> dict[str, int]:
        """Clear selection state globally or for one trusted chat/session scope."""

        if (chat_id is None) != (session_id is None):
            raise SelectionBindingMismatch("chat_id and session_id must be provided together")
        binding: tuple[str, str] | None = None
        if chat_id is not None:
            chat, session, _ = self._require_runtime_binding(chat_id, session_id)
            binding = (chat, session)
        removed = {"intents": 0, "tickets": 0, "used_tickets": 0}
        with self._state() as state:
            for bucket in removed:
                before = len(state[bucket])
                if binding is None:
                    state[bucket] = {}
                else:
                    state[bucket] = {
                        key: value for key, value in state[bucket].items()
                        if (value.get("chat_id"), value.get("session_id")) != binding
                    }
                removed[bucket] = before - len(state[bucket])
        return removed


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "MetaSelectionAuthorizer",
    "SelectionAuthorizationError",
    "SelectionBindingMismatch",
    "SelectionIntentNotFound",
    "SelectionTicketInvalid",
    "inventory_fingerprint",
    "normalize_selection_text",
    "resolve_selection_message",
    "sanitize_inventory",
]
