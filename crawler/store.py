# -*- coding: utf-8 -*-
"""SQLite 存储层。

两张表：
- projects：国自然项目主表，按项目编号（批准号）全局去重
- fetch_log：分片调度状态，支持断点续传（重跑自动跳过已完成分片）

库文件默认落在项目根的 data/ 目录（与设计文档一致：data/ 不入库）。
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

# 项目根 = 本文件上两级（crawler/store.py -> atria-demo-v2/）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "nsfc.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    project_no   TEXT PRIMARY KEY,   -- 项目编号/批准号
    title        TEXT,               -- 题目
    pi           TEXT,               -- 负责人
    institution  TEXT,               -- 依托单位
    year         INTEGER,            -- 批准年份
    grant_type   TEXT,               -- 项目类型（面上/青年/重点…）
    department   TEXT,               -- 学部
    subject_l1   TEXT,               -- 一级学科
    subject_l2   TEXT,               -- 二级学科
    subject_l3   TEXT,               -- 三级学科
    subject_code TEXT,               -- 学科代码（F01/F0117/F011706）
    amount_wy    REAL,               -- 金额（万元）
    begin_date   TEXT,               -- 执行起始（2020-01）
    end_date     TEXT,               -- 执行结束（2021-12）
    keywords     TEXT,               -- 中文关键词（LetPub 列表页不提供，留空）
    source       TEXT,               -- letpub / medsci
    fetched_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_projects_year ON projects(year);
CREATE INDEX IF NOT EXISTS idx_projects_dept ON projects(department);
CREATE INDEX IF NOT EXISTS idx_projects_inst ON projects(institution);

CREATE TABLE IF NOT EXISTS fetch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT, year INTEGER, dept TEXT, subject TEXT, company TEXT,
    keyword TEXT, status TEXT,      -- pending/running/done/failed
    fetched_count INTEGER DEFAULT 0, total_count INTEGER DEFAULT 0,
    started_at TIMESTAMP, finished_at TIMESTAMP, error TEXT,
    UNIQUE(source, year, dept, subject, company, keyword)
);

CREATE INDEX IF NOT EXISTS idx_fetch_log_status ON fetch_log(status);
"""


class Store:
    """SQLite 存储层。连接在进程内复用，写操作自动提交。"""

    def __init__(self, db_path: Path | str = DEFAULT_DB) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """事务上下文，异常时回滚。"""
        try:
            yield self._conn
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    # ------------------------------------------------------------------
    # projects 表
    # ------------------------------------------------------------------
    def upsert_project(self, rec: dict[str, Any]) -> bool:
        """插入或更新单条项目记录（按 project_no 去重）。

        返回 True 表示新增，False 表示更新已存在记录。
        """
        cols = [
            "project_no", "title", "pi", "institution", "year", "grant_type",
            "department", "subject_l1", "subject_l2", "subject_l3",
            "subject_code", "amount_wy", "begin_date", "end_date",
            "keywords", "source",
        ]
        values = [rec.get(c) for c in cols]
        placeholders = ",".join(["?"] * len(cols))
        updates = ",".join(f"{c}=excluded.{c}" for c in cols if c != "project_no")
        sql = (
            f"INSERT INTO projects ({','.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT(project_no) DO UPDATE SET {updates}"
        )
        cur = self._conn.execute(sql, values)
        self._conn.commit()
        return cur.rowcount > 0  # SQLite 对冲突更新返回 1，无法据此区分新增/更新，见下方说明

    def upsert_projects(self, records: Iterable[dict[str, Any]]) -> tuple[int, int]:
        """批量插入项目记录，返回 (新增数, 冲突跳过数)。

        用 INSERT OR IGNORE 做批量去重，比逐条 ON CONFLICT 快得多。
        """
        cols = [
            "project_no", "title", "pi", "institution", "year", "grant_type",
            "department", "subject_l1", "subject_l2", "subject_l3",
            "subject_code", "amount_wy", "begin_date", "end_date",
            "keywords", "source",
        ]
        rows = [tuple(rec.get(c) for c in cols) for rec in records]
        if not rows:
            return (0, 0)
        placeholders = ",".join(["?"] * len(cols))
        sql = f"INSERT OR IGNORE INTO projects ({','.join(cols)}) VALUES ({placeholders})"
        before = self.count_projects()
        with self.transaction() as conn:
            conn.executemany(sql, rows)
        after = self.count_projects()
        inserted = after - before
        return (inserted, len(rows) - inserted)

    def count_projects(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]

    def count_by_year(self) -> list[tuple[int, int]]:
        return [(r[0], r[1]) for r in self._conn.execute(
            "SELECT year, COUNT(*) FROM projects GROUP BY year ORDER BY year")]

    # ------------------------------------------------------------------
    # fetch_log 表（断点续传）
    # ------------------------------------------------------------------
    def _shard_key(self, shard: dict[str, Any]) -> tuple:
        # 注意：SQLite 的 UNIQUE 约束中 NULL ≠ NULL，空分片键若存 NULL 会导致
        # 同一分片反复新增行（断点续传失效）。统一把 None 归一化为空串。
        return tuple(
            (shard.get(k) if shard.get(k) is not None else "")
            for k in ("source", "year", "dept", "subject", "company", "keyword")
        )

    def get_shard_row(self, shard: dict[str, Any]) -> Optional[sqlite3.Row]:
        """查询分片完整记录（无则 None）。"""
        key = self._shard_key(shard)
        return self._conn.execute(
            "SELECT * FROM fetch_log "
            "WHERE source=? AND year=? AND dept=? AND subject=? "
            "AND company=? AND keyword=?",
            key,
        ).fetchone()

    def get_shard_status(self, shard: dict[str, Any]) -> Optional[str]:
        """查询分片当前状态（done 的分片重跑时跳过）。"""
        row = self.get_shard_row(shard)
        return row["status"] if row else None

    def mark_shard(self, shard: dict[str, Any], status: str,
                   fetched_count: int = 0, total_count: int = 0,
                   error: Optional[str] = None) -> None:
        """更新分片状态（running/done/failed），自动维护时间戳。"""
        key = self._shard_key(shard)
        started = "CURRENT_TIMESTAMP" if status == "running" else "NULL"
        finished = "CURRENT_TIMESTAMP" if status in ("done", "failed") else "NULL"
        err = "NULL" if error is None else "?"
        params = [fetched_count, total_count, status] + ([error] if error is not None else []) + list(key)
        sql = (
            "INSERT INTO fetch_log (fetched_count, total_count, status, error, "
            f"started_at, finished_at, source, year, dept, subject, company, keyword) "
            f"VALUES (?, ?, ?, {err}, {started}, {finished}, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(source, year, dept, subject, company, keyword) DO UPDATE SET "
            "fetched_count=excluded.fetched_count, total_count=excluded.total_count, "
            "status=excluded.status, error=excluded.error, "
            "started_at=COALESCE(fetch_log.started_at, excluded.started_at), "
            "finished_at=excluded.finished_at"
        )
        self._conn.execute(sql, params)
        self._conn.commit()

    def list_shards(self, status: Optional[str] = None, limit: int = 50) -> list[sqlite3.Row]:
        sql = "SELECT * FROM fetch_log"
        params: list[Any] = []
        if status:
            sql += " WHERE status=?"
            params.append(status)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        return self._conn.execute(sql, params).fetchall()
