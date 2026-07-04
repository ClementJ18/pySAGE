"""Unit tests for sage_ini.parser.io: file discovery and encoding-fallback reading.

The corpus mixes utf-8 and windows-1252 files; the reader must fall back through
ENCODINGS in order and report which encoding succeeded.
"""

from pathlib import Path

from sage_ini.parser.io import (
    ENCODINGS,
    INI_SUFFIXES,
    iter_ini_files,
    read_text,
    read_text_with_encoding,
)


class TestReadText:
    def test_reads_plain_ascii(self, tmp_path: Path):
        path = tmp_path / "plain.ini"
        path.write_bytes(b"Object MordorFighter\nEnd\n")

        text, encoding = read_text_with_encoding(path)

        assert text == "Object MordorFighter\nEnd\n"
        assert encoding == "utf-8-sig"

    def test_reads_utf8(self, tmp_path: Path):
        path = tmp_path / "utf8.ini"
        path.write_bytes("; héros\nEnd\n".encode())

        text, encoding = read_text_with_encoding(path)

        assert text == "; héros\nEnd\n"
        assert encoding == "utf-8-sig"

    def test_utf8_bom_is_stripped(self, tmp_path: Path):
        # corpus: credits.ini starts with a BOM that must never reach content
        path = tmp_path / "bom.ini"
        path.write_bytes(b"\xef\xbb\xbfObject A\nEnd\n")

        text, encoding = read_text_with_encoding(path)

        assert text == "Object A\nEnd\n"
        assert encoding == "utf-8-sig"

    def test_falls_back_to_windows_1252(self, tmp_path: Path):
        # 0x92 is a curly apostrophe in windows-1252 and an invalid start byte in utf-8
        path = tmp_path / "cp1252.ini"
        path.write_bytes(b"; the orc\x92s blade\nEnd\n")

        text, encoding = read_text_with_encoding(path)

        assert text == "; the orc’s blade\nEnd\n"
        assert encoding == "windows-1252"

    def test_never_fails_on_arbitrary_bytes(self, tmp_path: Path):
        # latin-1 is the terminal fallback and decodes any byte sequence; the
        # reader must always return text for an existing file, never raise.
        path = tmp_path / "binaryish.ini"
        path.write_bytes(bytes(range(256)))

        text, encoding = read_text_with_encoding(path)

        assert isinstance(text, str)
        assert encoding in ENCODINGS

    def test_read_text_returns_text_only(self, tmp_path: Path):
        path = tmp_path / "plain.ini"
        path.write_bytes(b"End\n")

        assert read_text(path) == "End\n"

    def test_missing_file_raises(self, tmp_path: Path):
        # Programmer error (invalid API use), not malformed input: raising is correct.
        try:
            read_text(tmp_path / "does_not_exist.ini")
        except FileNotFoundError:
            return
        raise AssertionError("expected FileNotFoundError")


class TestIterIniFiles:
    def test_finds_ini_inc_bhav_recursively(self, tmp_path: Path):
        (tmp_path / "sub").mkdir()
        wanted = [
            tmp_path / "a.ini",
            tmp_path / "b.inc",
            tmp_path / "sub" / "c.bhav",
            tmp_path / "sub" / "d.INI",  # extension match is case-insensitive
        ]
        unwanted = [
            tmp_path / "readme.txt",
            tmp_path / "sub" / "model.w3d",
        ]
        for p in wanted + unwanted:
            p.write_bytes(b"")

        found = list(iter_ini_files(tmp_path))

        assert found == sorted(wanted)

    def test_suffixes_constant_matches_corpus_extensions(self):
        assert INI_SUFFIXES == frozenset({".ini", ".inc", ".bhav"})

    def test_empty_directory_yields_nothing(self, tmp_path: Path):
        assert list(iter_ini_files(tmp_path)) == []
