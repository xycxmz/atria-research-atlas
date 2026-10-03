# -*- coding: utf-8 -*-
"""serve_api 的产物就绪契约（V2-011）：缺/损产物不得以 200 空对象冒充有效分析。

运行：
  python -m unittest discover -s tests -t . -k ServeApi
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import serve_api  # noqa: E402


class TestProductContract(unittest.TestCase):
    """readiness / ProductError 的三态与结构化错误。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.root = root
        self._saved_artifacts = serve_api.ARTIFACTS
        serve_api.ARTIFACTS = [
            ("unified_db", root / "unified.db", "core"),
            ("analysis", root / "analysis.json", "core"),
            ("advanced", root / "analysis_advanced.json", "core"),
            ("national", root / "national.json", "aux"),
            ("recent", root / "recent.json", "aux"),
        ]

    def tearDown(self):
        self._tmp.cleanup()
        serve_api.ARTIFACTS = self._saved_artifacts

    def _write(self, name: str, payload: object) -> None:
        p = self.root / name
        p.write_text(payload if isinstance(payload, str) else json.dumps(payload),
                     encoding="utf-8")

    def test_empty_dir_is_unavailable(self):
        r = serve_api.readiness()
        self.assertEqual(r["status"], "unavailable")
        self.assertEqual(sorted(r["missing"]),
                         ["advanced", "analysis", "national", "recent", "unified_db"])
        self.assertEqual(r["corrupt"], [])

    def test_core_ok_aux_missing_is_partial(self):
        (self.root / "unified.db").write_bytes(b"sqlite-ish")
        self._write("analysis.json", {"meta": {}})
        self._write("analysis_advanced.json", {})
        r = serve_api.readiness()
        self.assertEqual(r["status"], "partial")
        self.assertEqual(sorted(r["missing"]), ["national", "recent"])

    def test_all_present_is_ready(self):
        (self.root / "unified.db").write_bytes(b"sqlite-ish")
        self._write("analysis.json", {"meta": {}})
        self._write("analysis_advanced.json", {})
        self._write("national.json", {})
        self._write("recent.json", {})
        self.assertEqual(serve_api.readiness()["status"], "ready")

    def test_corrupt_core_is_unavailable(self):
        (self.root / "unified.db").write_bytes(b"sqlite-ish")
        self._write("analysis.json", "{ 这不是合法 JSON")
        self._write("analysis_advanced.json", {})
        r = serve_api.readiness()
        self.assertEqual(r["status"], "unavailable")
        self.assertEqual(r["corrupt"], ["analysis"])

    def test_snapshot_hashes_cached_by_size_mtime(self):
        (self.root / "unified.db").write_bytes(b"sqlite-ish")
        a = serve_api.snapshot_versions()
        b = serve_api.snapshot_versions()
        self.assertEqual(a, b)
        self.assertEqual(len(a["unified_db"]), 12)
        # 内容变化后缓存应失效（mtime 至少变化，或字节不同导致 size 不同）
        (self.root / "unified.db").write_bytes(b"different bytes here")
        c = serve_api.snapshot_versions()
        self.assertNotEqual(a["unified_db"], c["unified_db"])

    def test_load_json_missing_raises(self):
        with self.assertRaises(serve_api.ProductError) as cm:
            serve_api.load_json("nope.json", directory=self.root)
        self.assertEqual(cm.exception.kind, "missing")

    def test_load_json_corrupt_raises(self):
        self._write("broken.json", "{ broken")
        with self.assertRaises(serve_api.ProductError) as cm:
            serve_api.load_json("broken.json", directory=self.root)
        self.assertEqual(cm.exception.kind, "corrupt")

    def test_load_json_ok(self):
        self._write("ok.json", {"a": 1})
        self.assertEqual(serve_api.load_json("ok.json", directory=self.root), {"a": 1})


class TestStaticHosting(unittest.TestCase):
    """生产静态托管（V2-012）：dist 文件服务、SPA 回退、防穿越、未构建提示。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.root = root
        dist = root / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<html>app</html>", encoding="utf-8")
        (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
        self._saved_static = serve_api.STATIC_DIR
        serve_api.STATIC_DIR = dist

    def tearDown(self):
        self._tmp.cleanup()
        serve_api.STATIC_DIR = self._saved_static

    def test_root_and_asset(self):
        p, why = serve_api.pick_static("/")
        self.assertEqual(p.name, "index.html")
        self.assertEqual(why, "file")
        p, why = serve_api.pick_static("/assets/app.js")
        self.assertEqual(p.name, "app.js")
        self.assertEqual(why, "file")

    def test_unknown_path_falls_back_to_index(self):
        p, why = serve_api.pick_static("/whatever/deep/link")
        self.assertEqual(p.name, "index.html")
        self.assertEqual(why, "fallback")

    def test_traversal_blocked(self):
        p, why = serve_api.pick_static("../../../../etc/passwd")
        self.assertEqual(why, "fallback")
        self.assertTrue(str(p).endswith("index.html"))

    def test_missing_dist_reports_unbuilt(self):
        serve_api.STATIC_DIR = self.root / "no-dist"
        p, why = serve_api.pick_static("/")
        self.assertIsNone(p)
        self.assertEqual(why, "unbuilt")
        self.assertIn(b"\xe5\x89\x8d\xe7\xab\xaf\xe6\x9c\xaa\xe6\x9e\x84\xe5\xbb\xba", serve_api.UNBUILT_HTML)


class TestConfigure(unittest.TestCase):
    """configure() 重绑目录后，所有路径读取都须跟随（V2-012 打包时 load_json
    的默认参数曾停留在旧目录，导致演示包 /api/analysis 报 missing）。"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "analysis").mkdir()
        (self.root / "analysis" / "ok.json").write_text('{"k": 1}', encoding="utf-8")
        self._saved = (serve_api.UNIFIED_DB, serve_api.ANALYSIS_DIR,
                       serve_api.NATIONAL_DIR, serve_api.ARTIFACTS, serve_api.DB_PATH)
        serve_api.configure(data_dir=self.root)

    def tearDown(self):
        serve_api.UNIFIED_DB, serve_api.ANALYSIS_DIR, serve_api.NATIONAL_DIR, \
            serve_api.ARTIFACTS, serve_api.DB_PATH = self._saved
        self._tmp.cleanup()

    def test_load_json_follows_configured_dir(self):
        self.assertEqual(serve_api.load_json("ok.json"), {"k": 1})

    def test_explicit_directory_still_wins(self):
        other = self.root / "other"
        other.mkdir()
        (other / "x.json").write_text('{"x": 2}', encoding="utf-8")
        self.assertEqual(serve_api.load_json("x.json", directory=other), {"x": 2})

    def test_artifacts_and_readiness_follow(self):
        keys = [k for k, _, _ in serve_api.ARTIFACTS]
        self.assertEqual(keys, ["unified_db", "analysis", "advanced", "national", "recent"])
        self.assertTrue(all(p.is_relative_to(self.root) for _, p, _ in serve_api.ARTIFACTS))
        r = serve_api.readiness()
        # 只有 analysis 目录有 ok.json；analysis.json 未生成 → core 缺 → unavailable
        self.assertEqual(r["status"], "unavailable")


class TestPackageBareRun(unittest.TestCase):
    """V2R2-005：演示包内裸跑（python serve_api.py 不带 --data-dir/--static-dir）
    不能隐式落到开发仓库路径——自带 data/ 与 dist/ 时必须自动适配，否则全 503。"""

    def test_auto_detect_self_contained_layout(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "data" / "analysis").mkdir(parents=True)
            (root / "data" / "unified.db").write_bytes(b"")
            (root / "dist").mkdir()
            (root / "dist" / "index.html").write_text("<html>", encoding="utf-8")
            self.assertEqual(serve_api.default_run_dirs(root), (root / "data", root / "dist"))

    def test_dev_layout_not_auto_detected(self):
        # 无自包含布局（如仓库 tools/ 目录）→ None，沿用模块级仓库默认值
        with tempfile.TemporaryDirectory() as t:
            self.assertEqual(serve_api.default_run_dirs(Path(t)), (None, None))

    def test_partial_layout_not_auto_detected(self):
        # 只有 data 没有 dist（或反之）不算自包含包，不猜
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            (root / "data").mkdir()
            (root / "data" / "unified.db").write_bytes(b"")
            self.assertEqual(serve_api.default_run_dirs(root), (None, None))


if __name__ == "__main__":
    raise SystemExit(unittest.main(verbosity=2))
