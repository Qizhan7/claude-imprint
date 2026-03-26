import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

import memory_manager as mem
from chat_cleaner import parse_conversations, split_by_gap


class MemoryManagerReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

        self.old_db = mem.DB_PATH
        self.old_index = mem.MEMORY_INDEX
        self.old_bank_dir = mem.BANK_DIR
        self.old_embed = mem._embed

        mem.DB_PATH = self.root / "memory.db"
        mem.MEMORY_INDEX = self.root / "MEMORY.md"
        mem.BANK_DIR = self.root / "bank"
        mem.BANK_DIR.mkdir(parents=True, exist_ok=True)
        mem._embed = lambda text: None

        db = mem._get_db()
        db.close()

    def tearDown(self):
        mem.DB_PATH = self.old_db
        mem.MEMORY_INDEX = self.old_index
        mem.BANK_DIR = self.old_bank_dir
        mem._embed = self.old_embed
        self.temp_dir.cleanup()

    def test_update_and_delete_keep_index_in_sync(self):
        mem.remember("hello world", category="facts")

        updated = mem.update_memory(1, "changed world", "experience", 8)
        self.assertTrue(updated["ok"])
        self.assertIn("changed world", mem.MEMORY_INDEX.read_text(encoding="utf-8"))
        self.assertNotIn("hello world", mem.MEMORY_INDEX.read_text(encoding="utf-8"))

        deleted = mem.delete_memory(1)
        self.assertTrue(deleted["ok"])
        self.assertIn("*0 memories*", mem.MEMORY_INDEX.read_text(encoding="utf-8"))

    def test_bank_reindex_cleans_stale_template_rows(self):
        bank_file = mem.BANK_DIR / "preferences.md"
        bank_file.write_text("# Preferences\n\n<!-- template only -->\n", encoding="utf-8")

        db = mem._get_db()
        db.execute(
            """INSERT INTO bank_chunks
               (file_path, chunk_text, embedding, file_mtime, index_version)
               VALUES (?, ?, ?, ?, ?)""",
            (str(bank_file), "# Preferences\n\n<!-- template only -->", None, bank_file.stat().st_mtime, 1),
        )
        db.commit()
        db.close()

        mem._index_bank_files()

        con = sqlite3.connect(str(mem.DB_PATH))
        try:
            rows = con.execute("SELECT file_path, chunk_text, index_version FROM bank_chunks").fetchall()
        finally:
            con.close()
        self.assertEqual(rows, [])


class ChatCleanerReleaseTests(unittest.TestCase):
    def test_mixed_timestamp_formats_normalize_without_crashing(self):
        sample = [
            {
                "messages": [
                    {"role": "user", "text": "hi", "created_at": 1710028800},
                    {"role": "assistant", "text": "hello", "created_at": "2024-03-10T00:00:00Z"},
                ]
            }
        ]

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(sample, f)
            path = f.name

        try:
            conversations = parse_conversations(path)
            sessions = split_by_gap(conversations)
        finally:
            Path(path).unlink(missing_ok=True)

        self.assertEqual(len(conversations), 1)
        self.assertEqual(len(sessions), 1)
        self.assertEqual(len(sessions[0]), 2)
        self.assertIsNone(sessions[0][0]["ts"].tzinfo)
        self.assertEqual(sessions[0][0]["ts"], sessions[0][1]["ts"])


if __name__ == "__main__":
    unittest.main()
