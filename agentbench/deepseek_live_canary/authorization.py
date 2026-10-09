"""未来单次 replacement 预检的授权和持久化账本。

信任密钥与授权文件由未来独立批准的操作者提供，本模块不签发授权、不读
环境变量。SQLite FULL 同步事务先消费授权，再允许 HTTP；UNKNOWN 永不重试。
这防止意外伪造/不一致，不防御控制信任锚、账本备份或本机代码的攻击者。
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import hmac
import json
from pathlib import Path
import re
import sqlite3
import subprocess
from typing import Any
from uuid import uuid4

PREDECESSOR = "d92b541263edea9b749ff70f475fc4aad5b2fce0"
_VERIFIED = object()
INTENT_FIELDS = {"schema_version", "stage", "kind", "run_id", "token_id", "harness_sha",
                 "approval_reference", "transport_mode", "predecessor_result_commit"}
LEDGER_SCHEMA = "researchci.ds1.precheck-ledger.v1"


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical(value).encode()).hexdigest()


@dataclass(frozen=True)
class RepositoryState:
    head: str
    remote_head: str
    branch: str
    clean: bool


def read_repository_state(root: str | Path) -> RepositoryState:
    """仅读取本地 Git，不 fetch、不联网、不执行外部 hooks。"""
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
    return RepositoryState(git("rev-parse", "HEAD"), git("rev-parse", "origin/main"),
                           git("branch", "--show-current"), not git("status", "--porcelain", "--untracked-files=all"))


def validate_repository(state: RepositoryState, harness_sha: str) -> None:
    if not isinstance(state, RepositoryState) or state.branch != "main" or state.clean is not True or state.head != harness_sha or state.remote_head != harness_sha:
        raise RuntimeError("harness SHA/remote main/clean worktree gate denied")


@dataclass(frozen=True)
class VerifiedAuthorization:
    payload: str
    authorization_hash: str
    _proof: Any = field(repr=False)

    @property
    def intent(self) -> dict[str, Any]:
        return json.loads(self.payload)


class AuthorizationVerifier:
    """显式信任锚验证 HMAC，不提供签发入口或内置线上信任锚。"""

    def __init__(self, trusted_signing_key: bytes):
        if not isinstance(trusted_signing_key, bytes) or len(trusted_signing_key) < 16:
            raise ValueError("external trust anchor required")
        self._key = trusted_signing_key

    def verify(self, authorization: Any, *, run_id: str, harness_sha: str, transport_mode: str) -> VerifiedAuthorization:
        if not isinstance(authorization, dict) or set(authorization) != {"intent", "signature"}:
            raise ValueError("explicit signed authorization required")
        intent, signature = authorization["intent"], authorization["signature"]
        if not isinstance(intent, dict) or set(intent) != INTENT_FIELDS or not isinstance(signature, str):
            raise ValueError("invalid authorization schema")
        payload = canonical(intent)
        expected = hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("untrusted authorization signature")
        if (type(intent["schema_version"]) is not int or intent["schema_version"] != 1 or
            intent["stage"] != "PRECHECK_ONLY" or intent["kind"] != "REPLACEMENT" or
            intent["predecessor_result_commit"] != PREDECESSOR or intent["transport_mode"] != transport_mode or
            transport_mode not in {"MOCK_HTTP", "LIVE_HTTP"} or
            intent["run_id"] != run_id or intent["harness_sha"] != harness_sha or
            not re.fullmatch(r"[0-9a-f]{40}", harness_sha)):
            raise ValueError("authorization stage/run/harness/transport mismatch")
        for key in ("run_id", "token_id"):
            if not isinstance(intent[key], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", intent[key]):
                raise ValueError("invalid immutable run/token identity")
        if not isinstance(intent["approval_reference"], str) or not intent["approval_reference"].strip():
            raise ValueError("operator approval reference missing")
        return VerifiedAuthorization(payload, digest(authorization), _VERIFIED)


class OneUseLedger:
    """跨线程/进程的唯一授权消费；任何已有记录都拒绝第二次 reserve。"""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (token_id TEXT PRIMARY KEY, run_id TEXT UNIQUE NOT NULL, authorization_hash TEXT UNIQUE NOT NULL, intent TEXT NOT NULL, session_id TEXT NOT NULL, state TEXT NOT NULL, result TEXT)")
            db.execute("CREATE TABLE IF NOT EXISTS events (token_id TEXT NOT NULL, sequence INTEGER NOT NULL, event TEXT NOT NULL, previous_hash TEXT, event_hash TEXT NOT NULL, PRIMARY KEY(token_id,sequence))")
            db.execute("CREATE TABLE IF NOT EXISTS schema_info (version TEXT PRIMARY KEY)")
            versions = db.execute("SELECT version FROM schema_info").fetchall()
            if versions and versions != [(LEDGER_SCHEMA,)]:
                raise RuntimeError("ledger schema mismatch")
            db.execute("INSERT OR IGNORE INTO schema_info VALUES (?)", (LEDGER_SCHEMA,))

    @contextmanager
    def _transaction(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except sqlite3.Error as error:
            db.rollback()
            raise RuntimeError("ledger unavailable or already consumed") from error
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _event(self, db, token_id: str, event: dict[str, Any]) -> None:
        last = db.execute("SELECT sequence,event_hash FROM events WHERE token_id=? ORDER BY sequence DESC LIMIT 1", (token_id,)).fetchone()
        sequence, previous = (last[0] + 1, last[1]) if last else (1, None)
        event_hash = digest({"sequence": sequence, "previous_hash": previous, "event": event})
        db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (token_id, sequence, canonical(event), previous, event_hash))

    def reserve(self, approval: VerifiedAuthorization) -> "Reservation":
        if not isinstance(approval, VerifiedAuthorization) or approval._proof is not _VERIFIED:
            raise RuntimeError("verified authorization required")
        intent, session_id = approval.intent, uuid4().hex
        with self._transaction() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,NULL)", (intent["token_id"], intent["run_id"],
                       approval.authorization_hash, approval.payload, session_id, "RESERVED"))
            self._event(db, intent["token_id"], {"state": "RESERVED", "authorization_hash": approval.authorization_hash,
                                              "run_id": intent["run_id"], "harness_sha": intent["harness_sha"]})
        reservation = Reservation(self, approval, session_id)
        reservation.validate("RESERVED")
        return reservation

    def read(self, token_id: str) -> dict[str, Any]:
        with self._transaction() as db:
            row = db.execute("SELECT run_id,authorization_hash,intent,session_id,state,result FROM runs WHERE token_id=?", (token_id,)).fetchone()
            if row is None:
                raise RuntimeError("reservation missing")
            events = db.execute("SELECT sequence,event,previous_hash,event_hash FROM events WHERE token_id=? ORDER BY sequence", (token_id,)).fetchall()
            previous = None
            for expected_index, (index, event, prev_hash, event_hash) in enumerate(events, start=1):
                parsed = json.loads(event)
                if index != expected_index or prev_hash != previous or event_hash != digest({"sequence": index, "previous_hash": previous, "event": parsed}):
                    raise RuntimeError("ledger event integrity mismatch")
                previous = event_hash
            if not events or json.loads(events[-1][1]).get("state") != row[4]:
                raise RuntimeError("ledger state mismatch")
            return dict(zip(("run_id", "authorization_hash", "intent", "session_id", "state", "result"), row))


@dataclass(frozen=True)
class Reservation:
    ledger: OneUseLedger
    approval: VerifiedAuthorization
    session_id: str

    @property
    def intent(self) -> dict[str, Any]:
        return self.approval.intent

    def validate(self, state: str) -> None:
        if self.approval._proof is not _VERIFIED:
            raise RuntimeError("reservation proof invalid")
        row = self.ledger.read(self.intent["token_id"])
        if row["state"] != state or row["session_id"] != self.session_id or row["authorization_hash"] != self.approval.authorization_hash or row["intent"] != self.approval.payload:
            raise RuntimeError("reservation identity/state denied")

    def transition(self, expected: str, state: str, result: dict[str, Any] | None = None) -> None:
        self.validate(expected)
        with self.ledger._transaction() as db:
            changed = db.execute("UPDATE runs SET state=?,result=? WHERE token_id=? AND session_id=? AND state=?",
                                 (state, canonical(result) if result is not None else None, self.intent["token_id"], self.session_id, expected)).rowcount
            if changed != 1:
                raise RuntimeError("single-use state transition denied")
            self.ledger._event(db, self.intent["token_id"], {"state": state, "result": result})
        self.validate(state)

    def begin_http(self) -> None:
        self.transition("RESERVED", "HTTP_STARTED")

    def deny_canary(self) -> None:
        raise RuntimeError("PRECHECK_ONLY never authorizes responses or canary")
