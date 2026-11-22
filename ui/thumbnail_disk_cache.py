"""Persistent SQLite WAL cache for canonical-size packed thumbnails."""

from collections import OrderedDict
import os
from pathlib import Path
import sqlite3
from threading import Condition, Lock, Thread, current_thread
import time

from ui.thumbnail_history import PackedThumbnail

THUMBNAIL_DB_FILENAME = "thumbnails.db"
SCHEMA_VERSION = 1
ENTRY_OVERHEAD = 160
MAX_PENDING_PUTS = 256
MAX_PENDING_TOUCHES = 512
BATCH_SIZE = 32
BATCH_DELAY_SECONDS = 0.25
TOUCH_INTERVAL_SECONDS = 86400
MAX_READ_POOL = 8


def _normalize_key(path):
    if not path:
        return ""
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _folder_key(path_key):
    return os.path.dirname(path_key)


def _prefix_range(folder_path):
    key = _normalize_key(folder_path)
    prefix = os.path.join(key, "")
    upper = prefix[:-1] + chr(ord(prefix[-1]) + 1)
    return key, prefix, upper


def _matches_tree(path_key, tree_key, tree_prefix):
    return path_key == tree_key or path_key.startswith(tree_prefix)


def _is_valid_fingerprint(fingerprint):
    return (
        isinstance(fingerprint, tuple)
        and len(fingerprint) == 3
        and all(type(part) is int for part in fingerprint)
    )


def _is_lock_error(exc):
    code = getattr(exc, "sqlite_errorcode", None)
    if code is not None and (code & 0xFF) in (
        getattr(sqlite3, "SQLITE_BUSY", 5),
        getattr(sqlite3, "SQLITE_LOCKED", 6),
    ):
        return True
    message = str(exc).lower()
    return "locked" in message or "busy" in message


def _is_corruption_error(exc):
    if _is_lock_error(exc):
        return False
    code = getattr(exc, "sqlite_errorcode", None)
    if code is not None and (code & 0xFF) in (
        getattr(sqlite3, "SQLITE_CORRUPT", 11),
        getattr(sqlite3, "SQLITE_FORMAT", 24),
        getattr(sqlite3, "SQLITE_NOTADB", 26),
    ):
        return True
    message = str(exc).lower()
    return (
        "malformed" in message
        or "not a database" in message
        or "database disk image" in message
        or "corrupt" in message
    )


class _ResetRequiredError(Exception):
    """Raised when the cache schema or database header needs recreation."""


class ThumbnailDiskCache:
    """Thread-safe, bounded SQLite WAL cache for canonical packed thumbnails."""

    def __init__(self, cache_dir, byte_limit, *, enabled=True):
        self.cache_dir = os.path.normpath(os.path.abspath(cache_dir)) if cache_dir else ""
        self.db_path = (
            os.path.join(self.cache_dir, THUMBNAIL_DB_FILENAME) if self.cache_dir else ""
        )
        self._enabled = bool(enabled and self.db_path)
        self._byte_limit = max(0, int(byte_limit))

        self._state_lock = Lock()
        self._state_cond = Condition(self._state_lock)
        self._seq = 0
        self._pending_puts = OrderedDict()
        self._pending_deletes = {}
        self._pending_delete_trees = {}
        self._pending_touches = set()
        self._inflight_puts = {}
        self._inflight_deletes = {}
        self._inflight_delete_trees = {}
        self._trim_requested = False
        self._trim_seq = 0
        self._flush_waiters = 0
        self._reset_requested = False
        self._stop_requested = False
        self._drop_pending_on_stop = False
        self._clearing = False
        self._closed = False
        self._writer_thread = None

        self._pool_lock = Lock()
        self._pool_cond = Condition(self._pool_lock)
        self._read_pool = []
        self._checked_out_readers = 0
        self._readers_blocked = False

    @property
    def enabled(self):
        return self._enabled

    @property
    def byte_limit(self):
        with self._state_lock:
            return self._byte_limit

    def set_limit(self, byte_limit):
        limit = max(0, int(byte_limit))
        with self._state_lock:
            old_limit = self._byte_limit
            self._byte_limit = limit
            if self._closed or not self._enabled or limit >= old_limit:
                return
            if os.path.isfile(self.db_path) or self._writer_thread is not None:
                self._seq += 1
                self._trim_requested = True
                self._trim_seq = self._seq
                if not self._clearing:
                    self._ensure_writer_locked()
                self._state_cond.notify_all()

    def _has_pending_locked(self):
        return bool(
            self._pending_puts
            or self._pending_deletes
            or self._pending_delete_trees
            or self._pending_touches
            or self._trim_requested
            or self._reset_requested
        )

    def _has_pending_up_to_locked(self, target_seq):
        if any(entry[5] <= target_seq for entry in self._pending_puts.values()):
            return True
        if any(seq <= target_seq for seq in self._pending_deletes.values()):
            return True
        if any(seq <= target_seq for seq in self._pending_delete_trees.values()):
            return True
        if self._trim_requested and self._trim_seq <= target_seq:
            return True
        if self._reset_requested:
            return True
        return False

    def _has_inflight_locked(self):
        return bool(
            self._inflight_puts
            or self._inflight_deletes
            or self._inflight_delete_trees
        )

    def _ensure_writer_locked(self):
        if self._closed or not self._enabled or self._clearing:
            return
        if self._writer_thread is not None and self._writer_thread.is_alive():
            return
        worker = Thread(
            target=self._writer_loop,
            name="A5ThumbnailDiskCacheWriter",
            daemon=True,
        )
        self._writer_thread = worker
        worker.start()

    def _overlay_state_locked(self, key):
        best_seq = 0
        best_kind = "db"
        best_value = None

        pending_put = self._pending_puts.get(key)
        if pending_put is not None and pending_put[5] > best_seq:
            best_seq = pending_put[5]
            best_kind = "put"
            best_value = pending_put

        inflight_put = self._inflight_puts.get(key)
        if inflight_put is not None and inflight_put[5] > best_seq:
            best_seq = inflight_put[5]
            best_kind = "put"
            best_value = inflight_put

        pending_del = self._pending_deletes.get(key)
        if pending_del is not None and pending_del > best_seq:
            best_seq = pending_del
            best_kind = "deleted"
            best_value = None

        inflight_del = self._inflight_deletes.get(key)
        if inflight_del is not None and inflight_del > best_seq:
            best_seq = inflight_del
            best_kind = "deleted"
            best_value = None

        for (tree_key, tree_prefix, _), tree_seq in self._pending_delete_trees.items():
            if tree_seq > best_seq and _matches_tree(key, tree_key, tree_prefix):
                best_seq = tree_seq
                best_kind = "deleted"
                best_value = None

        for (tree_key, tree_prefix, _), tree_seq in self._inflight_delete_trees.items():
            if tree_seq > best_seq and _matches_tree(key, tree_key, tree_prefix):
                best_seq = tree_seq
                best_kind = "deleted"
                best_value = None

        return best_kind, best_value

    def get(self, path, fingerprint, target_size):
        if not self._enabled or not path or not _is_valid_fingerprint(fingerprint):
            return None
        key = _normalize_key(path)
        with self._state_lock:
            if self._closed or self._clearing or self._reset_requested:
                return None
            state, entry = self._overlay_state_locked(key)
            if state == "deleted":
                return None
            if state == "put":
                _, entry_fp, entry_target, thumbnail, _, _ = entry
                if entry_fp == fingerprint and entry_target == target_size:
                    return thumbnail
                return None

        conn = self._checkout_reader()
        if conn is None:
            return None
        healthy = False
        now = int(time.time())
        try:
            row = conn.execute(
                """
                SELECT m.file_size, m.mtime_ns, m.birthtime_ns, m.target_size,
                       m.source_width, m.source_height, m.last_access, b.data
                FROM thumb_meta AS m
                JOIN thumb_blob AS b ON b.id = m.id
                WHERE m.path_key = ?
                """,
                (key,),
            ).fetchone()
            healthy = True
        except sqlite3.DatabaseError as exc:
            if _is_corruption_error(exc):
                self._request_reset()
            return None
        except sqlite3.Error:
            return None
        finally:
            self._checkin_reader(conn, healthy)

        if row is None:
            return None
        file_size, mtime_ns, birthtime_ns, row_target, src_w, src_h, last_access, raw = row
        if (file_size, mtime_ns, birthtime_ns) != fingerprint or row_target != target_size or not raw:
            return None
        if now - int(last_access) >= TOUCH_INTERVAL_SECONDS:
            with self._state_lock:
                if (
                    not self._closed
                    and not self._clearing
                    and key not in self._pending_deletes
                    and key not in self._inflight_deletes
                    and len(self._pending_touches) < MAX_PENDING_TOUCHES
                ):
                    self._pending_touches.add(key)
        return PackedThumbnail(int(src_w), int(src_h), bytes(raw))

    def get_folder_metadata(self, folder_path):
        if not self._enabled or not folder_path:
            return {}
        folder_key = _normalize_key(folder_path)
        folder_prefix = os.path.join(folder_key, "")

        with self._state_lock:
            if self._closed or self._clearing or self._reset_requested:
                return {}
            folder_deleted_seq = 0
            tree_snapshots = []
            for tree_map in (self._inflight_delete_trees, self._pending_delete_trees):
                for tree, seq in tree_map.items():
                    tree_key, tree_prefix, _ = tree
                    if folder_key == tree_key or folder_key.startswith(tree_prefix):
                        folder_deleted_seq = max(folder_deleted_seq, seq)
                    elif tree_prefix.startswith(folder_prefix) or tree_key.startswith(folder_prefix):
                        tree_snapshots.append((tree_key, tree_prefix, seq))

            key_events = {}
            for del_map in (self._inflight_deletes, self._pending_deletes):
                for key, seq in del_map.items():
                    if _folder_key(key) == folder_key:
                        prev = key_events.get(key)
                        if prev is None or seq > prev[0]:
                            key_events[key] = (seq, "deleted", None)

            for put_map in (self._inflight_puts, self._pending_puts):
                for key, entry in put_map.items():
                    if entry[0] == folder_key:
                        seq = entry[5]
                        prev = key_events.get(key)
                        if prev is None or seq > prev[0]:
                            key_events[key] = (seq, "put", entry)

        result = {}
        conn = self._checkout_reader()
        if conn is not None:
            healthy = False
            try:
                rows = conn.execute(
                    """
                    SELECT path_key, file_size, mtime_ns, birthtime_ns,
                           target_size, source_width, source_height
                    FROM thumb_meta
                    WHERE folder_key = ?
                    """,
                    (folder_key,),
                ).fetchall()
                healthy = True
                for path_key, file_size, mtime_ns, birthtime_ns, target_size, width, height in rows:
                    if folder_deleted_seq > 0:
                        continue
                    if any(_matches_tree(path_key, t_key, t_prefix) for t_key, t_prefix, _ in tree_snapshots):
                        continue
                    result[path_key] = (
                        (int(file_size), int(mtime_ns), int(birthtime_ns)),
                        int(target_size),
                        int(width),
                        int(height),
                    )
            except sqlite3.DatabaseError as exc:
                if _is_corruption_error(exc):
                    self._request_reset()
                result.clear()
            except sqlite3.Error:
                result.clear()
            finally:
                self._checkin_reader(conn, healthy)

        for key, (seq, kind, entry) in key_events.items():
            effective_floor = folder_deleted_seq
            for t_key, t_prefix, t_seq in tree_snapshots:
                if _matches_tree(key, t_key, t_prefix) and t_seq > effective_floor:
                    effective_floor = t_seq
            if seq <= effective_floor or kind == "deleted":
                result.pop(key, None)
            else:
                _, fingerprint, target_size, thumbnail, _, _ = entry
                result[key] = (
                    fingerprint,
                    target_size,
                    thumbnail.source_width,
                    thumbnail.source_height,
                )
        return result

    def put(self, path, fingerprint, target_size, thumbnail):
        if (
            not self._enabled
            or not path
            or not _is_valid_fingerprint(fingerprint)
            or thumbnail is None
            or not thumbnail.data
        ):
            return
        cost = ENTRY_OVERHEAD + len(thumbnail.data)
        key = _normalize_key(path)
        folder_key = _folder_key(key)
        now = int(time.time())
        with self._state_lock:
            if self._closed or self._clearing or cost > self._byte_limit:
                return
            self._seq += 1
            self._pending_deletes.pop(key, None)
            self._pending_touches.discard(key)
            if key in self._pending_puts:
                self._pending_puts.move_to_end(key)
            elif len(self._pending_puts) >= MAX_PENDING_PUTS:
                self._pending_puts.popitem(last=False)
            self._pending_puts[key] = (
                folder_key,
                fingerprint,
                int(target_size),
                thumbnail,
                now,
                self._seq,
            )
            self._ensure_writer_locked()
            self._state_cond.notify_all()

    def discard(self, path):
        if not self._enabled or not path:
            return
        key = _normalize_key(path)
        with self._state_lock:
            if self._closed or self._clearing:
                return
            self._seq += 1
            self._pending_puts.pop(key, None)
            self._pending_touches.discard(key)
            if os.path.isfile(self.db_path) or self._writer_thread is not None or self._inflight_puts:
                self._pending_deletes[key] = self._seq
                self._ensure_writer_locked()
            self._state_cond.notify_all()

    def discard_tree(self, path):
        if not self._enabled or not path:
            return
        tree = _prefix_range(path)
        tree_key, tree_prefix, _ = tree
        with self._state_lock:
            if self._closed or self._clearing:
                return
            self._seq += 1
            for existing in [k for k in self._pending_puts if _matches_tree(k, tree_key, tree_prefix)]:
                self._pending_puts.pop(existing, None)
            for existing in [k for k in self._pending_deletes if _matches_tree(k, tree_key, tree_prefix)]:
                self._pending_deletes.pop(existing, None)
            for existing in [k for k in self._pending_touches if _matches_tree(k, tree_key, tree_prefix)]:
                self._pending_touches.discard(existing)
            for existing in [t for t in self._pending_delete_trees if _matches_tree(t[0], tree_key, tree_prefix)]:
                self._pending_delete_trees.pop(existing, None)
            if os.path.isfile(self.db_path) or self._writer_thread is not None or self._inflight_puts:
                self._pending_delete_trees[tree] = self._seq
                self._ensure_writer_locked()
            self._state_cond.notify_all()

    def flush(self, timeout=2.0):
        with self._state_lock:
            if not self._enabled or self._closed:
                return True
            if not self._has_pending_locked() and not self._has_inflight_locked():
                return True
            target_seq = self._seq
            if os.path.isfile(self.db_path) or self._pending_puts or self._reset_requested or self._trim_requested:
                self._ensure_writer_locked()
            elif self._writer_thread is None or not self._writer_thread.is_alive():
                self._pending_deletes.clear()
                self._pending_delete_trees.clear()
                self._pending_touches.clear()
                self._trim_requested = False
                return True
            self._flush_waiters += 1
            try:
                self._state_cond.notify_all()
                deadline = time.monotonic() + max(0.0, float(timeout))
                while (
                    not self._closed
                    and not self._clearing
                    and (self._has_pending_up_to_locked(target_seq) or self._has_inflight_locked())
                    and self._writer_thread is not None
                    and self._writer_thread.is_alive()
                ):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    self._state_cond.wait(remaining)
                return not (
                    self._has_pending_up_to_locked(target_seq) or self._has_inflight_locked()
                )
            finally:
                self._flush_waiters -= 1

    def clear(self):
        with self._state_lock:
            self._clearing = True
            self._drop_pending_on_stop = True
            self._stop_requested = True
            self._pending_puts.clear()
            self._pending_deletes.clear()
            self._pending_delete_trees.clear()
            self._pending_touches.clear()
            self._trim_requested = False
            self._reset_requested = False
            worker = self._writer_thread
            self._state_cond.notify_all()
        if worker is not None and worker is not current_thread():
            worker.join(timeout=2.0)
        self._close_read_pool(block=True, wait=True)
        try:
            self.clear_directory(self.cache_dir)
        finally:
            self._unblock_read_pool()
            with self._state_lock:
                if self._writer_thread is worker and (worker is None or not worker.is_alive()):
                    self._writer_thread = None
                self._inflight_puts.clear()
                self._inflight_deletes.clear()
                self._inflight_delete_trees.clear()
                self._drop_pending_on_stop = False
                self._stop_requested = False
                self._clearing = False
                self._state_cond.notify_all()

    def close(self, timeout=2.0):
        with self._state_lock:
            self._closed = True
            self._stop_requested = True
            worker = self._writer_thread
            if worker is None or not worker.is_alive():
                self._pending_puts.clear()
                self._pending_deletes.clear()
                self._pending_delete_trees.clear()
                self._pending_touches.clear()
                self._trim_requested = False
                self._reset_requested = False
            self._state_cond.notify_all()
        if worker is not None and worker is not current_thread():
            worker.join(timeout=max(0.0, float(timeout)))
            with self._state_lock:
                if not worker.is_alive() and self._writer_thread is worker:
                    self._writer_thread = None
        self._close_read_pool(block=True, wait=True)

    def disk_usage_bytes(self):
        return self.directory_usage_bytes(self.cache_dir)

    @staticmethod
    def directory_usage_bytes(cache_dir):
        if not cache_dir:
            return 0
        base = os.path.join(os.path.abspath(cache_dir), THUMBNAIL_DB_FILENAME)
        total = 0
        for suffix in ("", "-wal", "-shm"):
            try:
                total += os.path.getsize(base + suffix)
            except OSError:
                pass
        return total

    @staticmethod
    def clear_directory(cache_dir):
        if not cache_dir:
            return
        base = os.path.join(os.path.abspath(cache_dir), THUMBNAIL_DB_FILENAME)
        paths = (base + "-wal", base + "-shm", base)
        locked = False
        for path in paths:
            if not os.path.exists(path):
                continue
            removed = False
            for attempt in range(4):
                try:
                    os.remove(path)
                    removed = True
                    break
                except FileNotFoundError:
                    removed = True
                    break
                except PermissionError:
                    if attempt < 3:
                        time.sleep(0.02)
                except OSError:
                    break
            if not removed and os.path.exists(path):
                locked = True

        if locked and os.path.exists(base):
            conn = None
            try:
                conn = sqlite3.connect(base, timeout=0.5, isolation_level=None)
                conn.execute("PRAGMA busy_timeout = 500")
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                conn.execute("BEGIN IMMEDIATE")
                if "thumb_blob" in tables:
                    conn.execute("DELETE FROM thumb_blob")
                if "thumb_meta" in tables:
                    conn.execute("DELETE FROM thumb_meta")
                conn.execute("COMMIT")
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("PRAGMA incremental_vacuum")
            except sqlite3.Error:
                if conn is not None and conn.in_transaction:
                    try:
                        conn.execute("ROLLBACK")
                    except sqlite3.Error:
                        pass
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except sqlite3.Error:
                        pass

    def _request_reset(self):
        with self._state_lock:
            if self._closed or self._clearing:
                return
            self._reset_requested = True
            self._ensure_writer_locked()
            self._state_cond.notify_all()

    def _checkout_reader(self):
        if not self._enabled or not os.path.isfile(self.db_path):
            return None
        with self._pool_lock:
            if self._readers_blocked or self._closed or self._clearing:
                return None
            if self._read_pool:
                conn = self._read_pool.pop()
                self._checked_out_readers += 1
                return conn
            self._checked_out_readers += 1

        conn = None
        try:
            uri = Path(self.db_path).as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, timeout=0.05, check_same_thread=False)
            conn.execute("PRAGMA query_only = ON")
            conn.execute("PRAGMA busy_timeout = 50")
            conn.execute("PRAGMA temp_store = MEMORY")
            conn.execute("PRAGMA cache_size = -2000")
            conn.execute("PRAGMA mmap_size = 0")
            return conn
        except Exception as exc:
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
            with self._pool_lock:
                self._checked_out_readers = max(0, self._checked_out_readers - 1)
                self._pool_cond.notify_all()
            if isinstance(exc, sqlite3.DatabaseError) and _is_corruption_error(exc):
                self._request_reset()
            return None

    def _checkin_reader(self, conn, healthy):
        discard_conn = None
        with self._pool_lock:
            self._checked_out_readers = max(0, self._checked_out_readers - 1)
            if (
                healthy
                and not self._readers_blocked
                and not self._closed
                and not self._clearing
                and len(self._read_pool) < MAX_READ_POOL
            ):
                self._read_pool.append(conn)
            else:
                discard_conn = conn
            self._pool_cond.notify_all()
        if discard_conn is not None:
            try:
                discard_conn.close()
            except sqlite3.Error:
                pass

    def _close_read_pool(self, *, block=False, wait=False):
        with self._pool_lock:
            if block:
                self._readers_blocked = True
            idle = list(self._read_pool)
            self._read_pool.clear()
        for conn in idle:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        if wait:
            with self._pool_lock:
                deadline = time.monotonic() + 1.0
                while self._checked_out_readers > 0:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    self._pool_cond.wait(remaining)

    def _unblock_read_pool(self):
        with self._pool_lock:
            self._readers_blocked = False
            self._pool_cond.notify_all()

    def _open_writer_connection(self):
        os.makedirs(self.cache_dir, exist_ok=True)
        conn = sqlite3.connect(
            self.db_path,
            timeout=0.05,
            isolation_level=None,
            check_same_thread=False,
        )
        try:
            conn.execute("PRAGMA busy_timeout = 100")
            page_count = conn.execute("PRAGMA page_count").fetchone()[0]
            if page_count == 0:
                conn.execute("PRAGMA auto_vacuum = INCREMENTAL")
            mode_row = conn.execute("PRAGMA journal_mode").fetchone()
            if not mode_row or str(mode_row[0]).lower() != "wal":
                conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA temp_store = MEMORY")
            conn.execute("PRAGMA cache_size = -4000")
            conn.execute("PRAGMA mmap_size = 0")

            version = conn.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if version not in (0, SCHEMA_VERSION):
                raise _ResetRequiredError("Incompatible schema version")
            if version == 0 and page_count > 0 and not {"thumb_meta", "thumb_blob"}.issubset(tables):
                raise _ResetRequiredError("Incompatible cache tables")
            if version != SCHEMA_VERSION or not {"thumb_meta", "thumb_blob"}.issubset(tables):
                conn.executescript(
                    f"""
                    CREATE TABLE IF NOT EXISTS thumb_meta (
                        id INTEGER PRIMARY KEY,
                        path_key TEXT NOT NULL UNIQUE,
                        folder_key TEXT NOT NULL,
                        file_size INTEGER NOT NULL,
                        mtime_ns INTEGER NOT NULL,
                        birthtime_ns INTEGER NOT NULL,
                        target_size INTEGER NOT NULL,
                        source_width INTEGER NOT NULL,
                        source_height INTEGER NOT NULL,
                        byte_size INTEGER NOT NULL,
                        last_access INTEGER NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_thumb_meta_folder ON thumb_meta(folder_key);
                    CREATE INDEX IF NOT EXISTS idx_thumb_meta_lru ON thumb_meta(last_access);
                    CREATE TABLE IF NOT EXISTS thumb_blob (
                        id INTEGER PRIMARY KEY,
                        data BLOB NOT NULL
                    );
                    PRAGMA user_version = {SCHEMA_VERSION};
                    """
                )
            total_bytes = conn.execute(
                "SELECT COALESCE(SUM(byte_size), 0) FROM thumb_meta"
            ).fetchone()[0]
            return conn, int(total_bytes)
        except Exception:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            raise

    def _reset_corrupt_store(self, writer_conn):
        if writer_conn is not None:
            try:
                writer_conn.close()
            except sqlite3.Error:
                pass
        self._close_read_pool(block=True, wait=True)
        try:
            self.clear_directory(self.cache_dir)
        finally:
            self._unblock_read_pool()
        return None, 0

    def _writer_loop(self):
        writer_conn = None
        total_bytes = 0
        commits_since_sum = 0
        try:
            while True:
                with self._state_lock:
                    while not self._has_pending_locked() and not self._stop_requested:
                        self._state_cond.wait()

                    if self._drop_pending_on_stop:
                        self._pending_puts.clear()
                        self._pending_deletes.clear()
                        self._pending_delete_trees.clear()
                        self._pending_touches.clear()
                        self._trim_requested = False
                        self._reset_requested = False
                        self._state_cond.notify_all()
                        break

                    if self._stop_requested and not self._has_pending_locked():
                        self._state_cond.notify_all()
                        break

                    if (
                        0 < len(self._pending_puts) < BATCH_SIZE
                        and not self._pending_deletes
                        and not self._pending_delete_trees
                        and not self._pending_touches
                        and not self._trim_requested
                        and not self._reset_requested
                        and not self._stop_requested
                        and self._flush_waiters == 0
                    ):
                        self._state_cond.wait(BATCH_DELAY_SECONDS)
                        if self._drop_pending_on_stop:
                            continue

                    if self._stop_requested and not self._has_pending_locked():
                        self._state_cond.notify_all()
                        break

                    if self._reset_requested:
                        self._reset_requested = False
                        do_reset = True
                        puts = OrderedDict()
                        touches = []
                        do_trim = False
                    else:
                        do_reset = False
                        do_trim = self._trim_requested
                        self._trim_requested = False
                        current_limit = self._byte_limit

                        self._inflight_delete_trees = dict(self._pending_delete_trees)
                        self._pending_delete_trees.clear()
                        self._inflight_deletes = dict(self._pending_deletes)
                        self._pending_deletes.clear()
                        touches = list(self._pending_touches)
                        self._pending_touches.clear()

                        puts = OrderedDict()
                        batch_cap = 64 if (self._stop_requested or len(self._pending_puts) > BATCH_SIZE) else BATCH_SIZE
                        while self._pending_puts and len(puts) < batch_cap:
                            key, entry = self._pending_puts.popitem(last=False)
                            puts[key] = entry
                        self._inflight_puts = dict(puts)

                if do_reset:
                    writer_conn, total_bytes = self._reset_corrupt_store(writer_conn)
                    with self._state_lock:
                        self._state_cond.notify_all()
                    continue

                needs_db = bool(puts or self._inflight_deletes or self._inflight_delete_trees or touches or do_trim)
                if not needs_db:
                    with self._state_lock:
                        self._inflight_puts.clear()
                        self._inflight_deletes.clear()
                        self._inflight_delete_trees.clear()
                        self._state_cond.notify_all()
                    continue

                if writer_conn is None and not puts and not do_trim and not os.path.isfile(self.db_path):
                    with self._state_lock:
                        self._inflight_puts.clear()
                        self._inflight_deletes.clear()
                        self._inflight_delete_trees.clear()
                        self._state_cond.notify_all()
                    continue

                evicted = False
                try:
                    if writer_conn is None:
                        writer_conn, total_bytes = self._open_writer_connection()
                        commits_since_sum = 0

                    writer_conn.execute("BEGIN IMMEDIATE")
                    try:
                        for tree_key, tree_prefix, tree_upper in self._inflight_delete_trees:
                            rows = writer_conn.execute(
                                """
                                SELECT id, byte_size FROM thumb_meta
                                WHERE path_key = ? OR (path_key >= ? AND path_key < ?)
                                """,
                                (tree_key, tree_prefix, tree_upper),
                            ).fetchall()
                            if rows:
                                ids = [(row[0],) for row in rows]
                                removed_bytes = sum(int(row[1]) for row in rows)
                                writer_conn.executemany("DELETE FROM thumb_blob WHERE id = ?", ids)
                                writer_conn.executemany("DELETE FROM thumb_meta WHERE id = ?", ids)
                                total_bytes = max(0, total_bytes - removed_bytes)

                        for del_key in self._inflight_deletes:
                            row = writer_conn.execute(
                                "SELECT id, byte_size FROM thumb_meta WHERE path_key = ?",
                                (del_key,),
                            ).fetchone()
                            if row is not None:
                                row_id, old_bytes = int(row[0]), int(row[1])
                                writer_conn.execute("DELETE FROM thumb_blob WHERE id = ?", (row_id,))
                                writer_conn.execute("DELETE FROM thumb_meta WHERE id = ?", (row_id,))
                                total_bytes = max(0, total_bytes - old_bytes)

                        for put_key, entry in puts.items():
                            folder_key, fingerprint, target_size, thumbnail, accessed_at, _ = entry
                            file_size, mtime_ns, birthtime_ns = fingerprint
                            data = thumbnail.data
                            byte_size = ENTRY_OVERHEAD + len(data)
                            if byte_size > current_limit:
                                continue
                            existing = writer_conn.execute(
                                "SELECT id, byte_size FROM thumb_meta WHERE path_key = ?",
                                (put_key,),
                            ).fetchone()
                            if existing is not None:
                                row_id, old_bytes = int(existing[0]), int(existing[1])
                                writer_conn.execute(
                                    """
                                    UPDATE thumb_meta
                                    SET folder_key = ?, file_size = ?, mtime_ns = ?, birthtime_ns = ?,
                                        target_size = ?, source_width = ?, source_height = ?,
                                        byte_size = ?, last_access = ?
                                    WHERE id = ?
                                    """,
                                    (
                                        folder_key, file_size, mtime_ns, birthtime_ns,
                                        target_size, thumbnail.source_width, thumbnail.source_height,
                                        byte_size, accessed_at, row_id,
                                    ),
                                )
                                writer_conn.execute(
                                    "INSERT OR REPLACE INTO thumb_blob (id, data) VALUES (?, ?)",
                                    (row_id, sqlite3.Binary(data)),
                                )
                                total_bytes = max(0, total_bytes + byte_size - old_bytes)
                            else:
                                cursor = writer_conn.execute(
                                    """
                                    INSERT INTO thumb_meta (
                                        path_key, folder_key, file_size, mtime_ns, birthtime_ns,
                                        target_size, source_width, source_height, byte_size, last_access
                                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                    """,
                                    (
                                        put_key, folder_key, file_size, mtime_ns, birthtime_ns,
                                        target_size, thumbnail.source_width, thumbnail.source_height,
                                        byte_size, accessed_at,
                                    ),
                                )
                                writer_conn.execute(
                                    "INSERT OR REPLACE INTO thumb_blob (id, data) VALUES (?, ?)",
                                    (cursor.lastrowid, sqlite3.Binary(data)),
                                )
                                total_bytes += byte_size

                        if touches:
                            now = int(time.time())
                            writer_conn.executemany(
                                "UPDATE thumb_meta SET last_access = ? WHERE path_key = ?",
                                [(now, touch_key) for touch_key in touches],
                            )

                        commits_since_sum += 1
                        if total_bytes > current_limit or commits_since_sum >= 16:
                            total_bytes = int(
                                writer_conn.execute(
                                    "SELECT COALESCE(SUM(byte_size), 0) FROM thumb_meta"
                                ).fetchone()[0]
                            )
                            commits_since_sum = 0

                        if total_bytes > current_limit:
                            target_bytes = int(current_limit * 0.9)
                            row_count = int(
                                writer_conn.execute("SELECT COUNT(*) FROM thumb_meta").fetchone()[0]
                            )
                            while total_bytes > target_bytes and not (
                                total_bytes <= current_limit and row_count <= 1
                            ):
                                victims = writer_conn.execute(
                                    """
                                    SELECT id, byte_size FROM thumb_meta
                                    ORDER BY last_access ASC, id ASC
                                    LIMIT 256
                                    """
                                ).fetchall()
                                if not victims:
                                    total_bytes = 0
                                    break
                                victim_ids = []
                                for row_id, row_bytes in victims:
                                    if total_bytes <= current_limit and row_count <= 1:
                                        break
                                    victim_ids.append((int(row_id),))
                                    total_bytes = max(0, total_bytes - int(row_bytes))
                                    row_count = max(0, row_count - 1)
                                    if total_bytes <= target_bytes:
                                        break
                                if not victim_ids:
                                    break
                                writer_conn.executemany(
                                    "DELETE FROM thumb_blob WHERE id = ?", victim_ids
                                )
                                writer_conn.executemany(
                                    "DELETE FROM thumb_meta WHERE id = ?", victim_ids
                                )
                                evicted = True

                        writer_conn.execute("COMMIT")
                    except Exception:
                        if writer_conn.in_transaction:
                            try:
                                writer_conn.execute("ROLLBACK")
                            except sqlite3.Error:
                                pass
                        raise

                    if evicted:
                        writer_conn.execute("PRAGMA incremental_vacuum(64)")
                except _ResetRequiredError:
                    writer_conn, total_bytes = self._reset_corrupt_store(writer_conn)
                except sqlite3.DatabaseError as exc:
                    if _is_corruption_error(exc):
                        writer_conn, total_bytes = self._reset_corrupt_store(writer_conn)
                    elif not _is_lock_error(exc):
                        # Disk full / I/O error: keep going cleanly without crashing.
                        if writer_conn is not None:
                            try:
                                writer_conn.close()
                            except sqlite3.Error:
                                pass
                            writer_conn = None
                except OSError:
                    if writer_conn is not None:
                        try:
                            writer_conn.close()
                        except sqlite3.Error:
                            pass
                        writer_conn = None
                finally:
                    with self._state_lock:
                        self._inflight_puts.clear()
                        self._inflight_deletes.clear()
                        self._inflight_delete_trees.clear()
                        self._state_cond.notify_all()
        finally:
            if writer_conn is not None:
                try:
                    writer_conn.close()
                except sqlite3.Error:
                    pass
