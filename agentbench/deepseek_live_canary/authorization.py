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
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import shutil
import tempfile
from typing import Any
from uuid import uuid4
import time
from .secure_io import checked_path, exclusive_json, private_directory, PathIdentity, owner_only

PREDECESSOR = "d92b541263edea9b749ff70f475fc4aad5b2fce0"
_VERIFIED = object()
INTENT_FIELDS = {"schema_version", "stage", "kind", "run_id", "token_id", "harness_sha",
                 "approval_reference", "transport_mode", "predecessor_result_commit"}
INTENT_V2_FIELDS = INTENT_FIELDS | {"key_id", "issued_at", "expires_at", "ledger_path"}
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
    checked_remote_head: str | None = None
    remote_checked_at: float | None = None


def read_repository_state(root: str | Path) -> RepositoryState:
    """git ls-remote 查询真实 refs/heads/main，绝不 checkout/reset/fetch。"""
    def git(*args: str) -> str:
        return subprocess.check_output(["git", "-C", str(root), *args], text=True, timeout=20, stderr=subprocess.DEVNULL).strip()
    remote = git("ls-remote", "--exit-code", "origin", "refs/heads/main").splitlines()
    if len(remote) != 1 or not re.fullmatch(r"[0-9a-f]{40}\s+refs/heads/main", remote[0]):
        raise RuntimeError("fresh remote main could not be verified")
    return RepositoryState(git("rev-parse", "HEAD"), git("rev-parse", "origin/main"),
                           git("branch", "--show-current"), not git("status", "--porcelain", "--untracked-files=all"), remote[0].split()[0], time.monotonic())


def validate_repository(state: RepositoryState, harness_sha: str, *, require_fresh: bool = False) -> None:
    if not isinstance(state, RepositoryState) or state.branch != "main" or state.clean is not True or state.head != harness_sha or state.remote_head != harness_sha:
        raise RuntimeError("harness SHA/remote main/clean worktree gate denied")
    if require_fresh and (state.checked_remote_head != harness_sha or state.remote_checked_at is None or not 0 <= time.monotonic() - state.remote_checked_at <= 30):
        raise RuntimeError("fresh remote SHA verification required")


@dataclass(frozen=True)
class VerifiedAuthorization:
    payload: str
    authorization_hash: str
    _proof: Any = field(repr=False)

    @property
    def intent(self) -> dict[str, Any]:
        return json.loads(self.payload)

    def validate(self) -> None:
        if not isinstance(self._proof, _AuthorizationProof):
            raise RuntimeError("verified authorization payload/proof mismatch")
        self._proof.validate(self)


@dataclass(frozen=True)
class _AuthorizationProof:
    authority: Any = field(repr=False)
    signed_document: str = field(repr=False)
    run_id: str
    harness_sha: str
    mode: str

    def validate(self, issued: VerifiedAuthorization) -> None:
        checked = self.authority.verify(json.loads(self.signed_document), run_id=self.run_id,
            harness_sha=self.harness_sha, transport_mode=self.mode)
        if checked.payload != issued.payload or checked.authorization_hash != issued.authorization_hash:
            raise RuntimeError("verified authorization payload/proof mismatch")


class AuthorizationVerifier:
    """显式信任锚验证 HMAC，不提供签发入口或内置线上信任锚。"""

    def __init__(self, trusted_signing_key: bytes | None = None, *, public_key_pem: bytes | None = None,
                 key_id: str = "operator", revoked_tokens=frozenset(), revoked_keys=frozenset(), clock=time.time):
        if public_key_pem is None and (not isinstance(trusted_signing_key, bytes) or len(trusted_signing_key) < 16):
            raise ValueError("external trust anchor required")
        if public_key_pem is not None and (trusted_signing_key is not None or not isinstance(public_key_pem, bytes)):
            raise ValueError("public-key verifier cannot accept a signing secret")
        self._key = trusted_signing_key
        self._public_key = public_key_pem
        self._key_id, self._revoked_tokens, self._revoked_keys, self._clock = key_id, frozenset(revoked_tokens), frozenset(revoked_keys), clock

    def _verify_public_signature(self, payload: str, signature: str) -> None:
        executable = shutil.which("openssl")
        if executable is None:
            raise RuntimeError("OpenSSL signature verifier unavailable")
        try:
            signature_bytes = bytes.fromhex(signature)
        except ValueError:
            raise ValueError("invalid public signature encoding") from None
        with tempfile.TemporaryDirectory(prefix="researchci-signature-") as directory:
            directory = private_directory(Path(directory))
            for name, data in (("public.pem", self._public_key), ("intent.json", payload.encode()), ("signature.bin", signature_bytes)):
                path = directory / name
                path.write_bytes(data)
                owner_only(path)
            result = subprocess.run([executable, "dgst", "-sha256", "-verify", str(directory/"public.pem"),
                "-signature", str(directory/"signature.bin"), str(directory/"intent.json")],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
            if result.returncode != 0:
                raise ValueError("untrusted public authorization signature")

    def verify(self, authorization: Any, *, run_id: str, harness_sha: str, transport_mode: str) -> VerifiedAuthorization:
        if not isinstance(authorization, dict) or set(authorization) != {"intent", "signature"}:
            raise ValueError("explicit signed authorization required")
        intent, signature = authorization["intent"], authorization["signature"]
        if not isinstance(intent, dict) or set(intent) != (INTENT_V2_FIELDS if intent.get("schema_version") == 2 else INTENT_FIELDS) or not isinstance(signature, str):
            raise ValueError("invalid authorization schema")
        payload = canonical(intent)
        if intent["schema_version"] == 2:
            if self._public_key is None or intent["key_id"] != self._key_id or intent["key_id"] in self._revoked_keys or intent["token_id"] in self._revoked_tokens:
                raise ValueError("unknown or revoked authorization authority")
            if type(intent["issued_at"]) is not int or type(intent["expires_at"]) is not int or not intent["issued_at"] <= self._clock() < intent["expires_at"] or not 0 < intent["expires_at"] - intent["issued_at"] <= 3600:
                raise ValueError("authorization expired or outside validity period")
            if not isinstance(intent["ledger_path"], str) or str(checked_path(intent["ledger_path"])) != intent["ledger_path"]:
                raise ValueError("authorization ledger path must be absolute")
            self._verify_public_signature(payload, signature)
        else:
            if self._key is None:
                raise ValueError("legacy authorization rejected by public-key trust anchor")
            expected = hmac.new(self._key, payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("untrusted authorization signature")
        if (type(intent["schema_version"]) is not int or intent["schema_version"] not in {1, 2} or
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
        return VerifiedAuthorization(payload, digest(authorization), _AuthorizationProof(self, canonical(authorization), run_id, harness_sha, transport_mode))


class OneUseLedger:
    """跨线程/进程的唯一授权消费；任何已有记录都拒绝第二次 reserve。"""

    def __init__(self, path: str | Path, *, timeout: float = 10):
        self.path = checked_path(path)
        self.timeout = timeout
        private_directory(self.path.parent)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        except FileExistsError:
            pass
        owner_only(self.path)
        self.identity = PathIdentity(self.path)
        self.claims = private_directory(self.path.with_name(self.path.name + ".claims"))
        self.claims_identity = PathIdentity(self.claims)
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
        self.identity.validate()
        self.claims_identity.validate()
        db = None
        try:
            db = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None)
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except sqlite3.Error as error:
            if db is not None: db.rollback()
            raise RuntimeError("ledger unavailable or already consumed") from error
        except BaseException:
            if db is not None: db.rollback()
            raise
        finally:
            if db is not None: db.close()

    def _event(self, db, token_id: str, event: dict[str, Any]) -> None:
        last = db.execute("SELECT sequence,event_hash FROM events WHERE token_id=? ORDER BY sequence DESC LIMIT 1", (token_id,)).fetchone()
        sequence, previous = (last[0] + 1, last[1]) if last else (1, None)
        event_hash = digest({"sequence": sequence, "previous_hash": previous, "event": event})
        db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (token_id, sequence, canonical(event), previous, event_hash))

    def reserve(self, approval: VerifiedAuthorization, *, repo_root: str | Path | None = None) -> "Reservation":
        if not isinstance(approval, VerifiedAuthorization):
            raise RuntimeError("verified authorization required")
        approval.validate()
        intent, session_id = approval.intent, uuid4().hex
        if intent["schema_version"] == 2 and intent["ledger_path"] != str(self.path):
            raise RuntimeError("authorization is bound to a different ledger")
        # 独立于数据库的不可覆盖 tombstone：数据库备份回滚也不能复用 token。
        self.claims_identity.validate()
        try:
            exclusive_json(self.claims / (hashlib.sha256(intent["token_id"].encode()).hexdigest() + ".json"),
                           {"authorization_hash": approval.authorization_hash, "run_id": intent["run_id"]})
        except FileExistsError as error:
            raise RuntimeError("authorization token already claimed") from error
        with self._transaction() as db:
            db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,NULL)", (intent["token_id"], intent["run_id"],
                       approval.authorization_hash, approval.payload, session_id, "RESERVED"))
            self._event(db, intent["token_id"], {"state": "RESERVED", "authorization_hash": approval.authorization_hash,
                                              "run_id": intent["run_id"], "intent": approval.payload, "session_id": session_id})
        reservation = Reservation(self, approval, session_id, str(Path(repo_root).resolve()) if repo_root is not None else None)
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
            first, last = json.loads(events[0][1]), json.loads(events[-1][1])
            if (first.get("run_id"), first.get("authorization_hash"), first.get("intent"), first.get("session_id")) != row[:4] or (canonical(last.get("result")) if last.get("result") is not None else None) != row[5]:
                raise RuntimeError("ledger immutable intent/result mismatch")
            return dict(zip(("run_id", "authorization_hash", "intent", "session_id", "state", "result"), row))


@dataclass(frozen=True)
class Reservation:
    ledger: OneUseLedger
    approval: VerifiedAuthorization
    session_id: str
    repo_root: str | None = None

    @property
    def intent(self) -> dict[str, Any]:
        return self.approval.intent

    def validate(self, state: str) -> None:
        self.approval.validate()
        row = self.ledger.read(self.intent["token_id"])
        if row["state"] != state or row["session_id"] != self.session_id or row["authorization_hash"] != self.approval.authorization_hash or row["intent"] != self.approval.payload:
            raise RuntimeError("reservation identity/state denied")

    def transition(self, expected: str, state: str, result: dict[str, Any] | None = None) -> None:
        if state not in {"RESERVED": {"HTTP_STARTED", "UNKNOWN"}, "HTTP_STARTED": {"RESULT_PERSISTED", "UNKNOWN"}}.get(expected, set()):
            raise RuntimeError("ledger terminal/backward transition denied")
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

    def validate_live_execution(self) -> None:
        self.approval.validate()
        if self.intent["schema_version"] != 2 or self.repo_root is None:
            raise RuntimeError("legacy/unsigned execution cannot enter live HTTP")
        validate_repository(read_repository_state(self.repo_root), self.intent["harness_sha"], require_fresh=True)

    def deny_canary(self) -> None:
        raise RuntimeError("PRECHECK_ONLY never authorizes responses or canary")
