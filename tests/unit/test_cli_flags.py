"""Tests for global CLI flags and error handling (Phase 2)."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from sophia.cli._output import OutputConfig, get_console, handle_cli_error, print_json_or_table
from sophia.domain.errors import AuthError, TopicExtractionError


class TestOutputConfig:
    """OutputConfig defaults and mutation."""

    def test_defaults(self) -> None:
        cfg = OutputConfig()
        assert cfg.json_mode is False
        assert cfg.quiet is False
        assert cfg.no_color is False
        assert cfg.debug is False

    def test_mutation(self) -> None:
        cfg = OutputConfig()
        cfg.json_mode = True
        cfg.debug = True
        assert cfg.json_mode is True
        assert cfg.debug is True


class TestGetConsole:
    """get_console() respects OutputConfig."""

    def test_no_color_passed_to_console(self) -> None:
        from sophia.cli._output import output

        output.no_color = True
        try:
            console = get_console()
            assert console.no_color is True
        finally:
            output.no_color = False

    def test_quiet_passed_to_console(self) -> None:
        from sophia.cli._output import output

        output.quiet = True
        try:
            console = get_console()
            assert console.quiet is True
        finally:
            output.quiet = False


class TestPrintJsonOrTable:
    """print_json_or_table switches on json_mode."""

    def test_json_mode_prints_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        from sophia.cli._output import output

        output.json_mode = True
        output.no_color = True
        try:
            data = [{"title": "Book A", "isbn": "123"}]
            print_json_or_table(data, table=None)
            captured = capsys.readouterr()
            parsed = json.loads(captured.out)
            assert parsed == data
        finally:
            output.json_mode = False
            output.no_color = False

    def test_table_mode_prints_table(self, capsys: pytest.CaptureFixture[str]) -> None:
        from rich.table import Table

        from sophia.cli._output import output

        output.json_mode = False
        output.no_color = True
        try:
            table = Table(title="Test")
            table.add_column("Col")
            table.add_row("val")
            print_json_or_table([], table=table)
            captured = capsys.readouterr()
            assert "val" in captured.out
        finally:
            output.no_color = False


class TestHandleCliError:
    """handle_cli_error produces friendly messages and exits."""

    def test_auth_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        from sophia.cli._output import output

        output.no_color = True
        try:
            with pytest.raises(SystemExit, match="1"):
                handle_cli_error(AuthError("expired"))
            captured = capsys.readouterr()
            assert "Not logged in" in captured.out
            assert "sophia auth login" in captured.out
        finally:
            output.no_color = False

    def test_connection_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        from sophia.cli._output import output

        output.no_color = True
        try:
            with pytest.raises(SystemExit, match="1"):
                handle_cli_error(httpx.ConnectError("refused"))
            captured = capsys.readouterr()
            assert "Connection failed" in captured.out
        finally:
            output.no_color = False

    def test_timeout_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        from sophia.cli._output import output

        output.no_color = True
        try:
            with pytest.raises(SystemExit, match="1"):
                handle_cli_error(httpx.TimeoutException("timed out"))
            captured = capsys.readouterr()
            assert "timed out" in captured.out
        finally:
            output.no_color = False

    def test_topic_extraction_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        from sophia.cli._output import output

        output.no_color = True
        try:
            with pytest.raises(SystemExit, match="1"):
                handle_cli_error(TopicExtractionError("LLM failed"))
            captured = capsys.readouterr()
            assert "Topic extraction failed" in captured.out
            assert "LLM failed" in captured.out
        finally:
            output.no_color = False

    def test_generic_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        from sophia.cli._output import output

        output.no_color = True
        try:
            with pytest.raises(SystemExit, match="1"):
                handle_cli_error(RuntimeError("something broke"))
            captured = capsys.readouterr()
            assert "something broke" in captured.out
        finally:
            output.no_color = False

    def test_debug_shows_traceback(self, capsys: pytest.CaptureFixture[str]) -> None:
        from sophia.cli._output import output

        output.no_color = True
        output.debug = True
        try:
            with pytest.raises(SystemExit, match="1"):
                try:
                    raise RuntimeError("debug test")
                except RuntimeError as exc:
                    handle_cli_error(exc)
            captured = capsys.readouterr()
            assert "Traceback" in captured.out or "RuntimeError" in captured.out
        finally:
            output.no_color = False
            output.debug = False


class TestMainFlagParsing:
    """main() parses global flags from sys.argv."""

    def test_json_flag_parsed(self) -> None:
        from sophia.cli._output import output

        with patch("sys.argv", ["sophia", "--json", "--help"]), pytest.raises(SystemExit):
            from sophia.__main__ import main

            main()
        assert output.json_mode is True
        output.json_mode = False

    def test_quiet_flag_parsed(self) -> None:
        from sophia.cli._output import output

        with patch("sys.argv", ["sophia", "--quiet", "--help"]), pytest.raises(SystemExit):
            from sophia.__main__ import main

            main()
        assert output.quiet is True
        output.quiet = False

    def test_no_color_flag_parsed(self) -> None:
        from sophia.cli._output import output

        with patch("sys.argv", ["sophia", "--no-color", "--help"]), pytest.raises(SystemExit):
            from sophia.__main__ import main

            main()
        assert output.no_color is True
        output.no_color = False

    def test_no_color_env_var(self) -> None:
        from sophia.cli._output import output

        with (
            patch("sys.argv", ["sophia", "--help"]),
            patch.dict("os.environ", {"NO_COLOR": "1"}),
            pytest.raises(SystemExit),
        ):
            from sophia.__main__ import main

            main()
        assert output.no_color is True
        output.no_color = False

    def test_debug_flag_parsed(self) -> None:
        from sophia.cli._output import output

        with patch("sys.argv", ["sophia", "--debug", "--help"]), pytest.raises(SystemExit):
            from sophia.__main__ import main

            main()
        assert output.debug is True
        output.debug = False

    def test_keyboard_interrupt_exits_130(self) -> None:
        with (
            patch("sys.argv", ["sophia", "books", "discover"]),
            patch("sophia.__main__.app", side_effect=KeyboardInterrupt),
            pytest.raises(SystemExit, match="130"),
        ):
            from sophia.__main__ import main

            main()

    def test_unhandled_exception_calls_error_handler(self) -> None:
        with (
            patch("sys.argv", ["sophia", "books", "discover"]),
            patch("sophia.__main__.app", side_effect=RuntimeError("boom")),
            patch("sophia.cli._output.output") as mock_output,
            pytest.raises(SystemExit),
        ):
            mock_output.no_color = True
            mock_output.quiet = False
            mock_output.debug = False
            mock_output.json_mode = False
            from sophia.__main__ import main

            main()


class TestCurrentSemester:
    """current_semester() infers TISS semester from the date."""

    def test_spring_semester(self) -> None:
        from datetime import date

        from sophia.cli._output import current_semester

        with patch("sophia.cli._output.date") as mock_date:
            mock_date.today.return_value = date(2026, 3, 15)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = current_semester()
        assert result == "2026S"

    def test_winter_semester_october(self) -> None:
        from datetime import date

        from sophia.cli._output import current_semester

        with patch("sophia.cli._output.date") as mock_date:
            mock_date.today.return_value = date(2025, 10, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = current_semester()
        assert result == "2025W"

    def test_winter_semester_january(self) -> None:
        from datetime import date

        from sophia.cli._output import current_semester

        with patch("sophia.cli._output.date") as mock_date:
            mock_date.today.return_value = date(2026, 1, 15)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = current_semester()
        assert result == "2025W"

    def test_summer_semester_june(self) -> None:
        from datetime import date

        from sophia.cli._output import current_semester

        with patch("sophia.cli._output.date") as mock_date:
            mock_date.today.return_value = date(2026, 6, 1)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            result = current_semester()
        assert result == "2026S"


class TestRequireTissSession:
    """require_tiss_session() loads settings and TISS session."""

    def test_returns_settings_and_creds(self) -> None:
        from unittest.mock import MagicMock

        from sophia.cli._output import require_tiss_session

        mock_settings = MagicMock()
        mock_settings.config_dir = "/tmp/sophia-test"
        mock_creds = MagicMock()

        with (
            patch("sophia.config.Settings", return_value=mock_settings),
            patch("sophia.adapters.auth.load_tiss_session", return_value=mock_creds),
            patch("sophia.adapters.auth.tiss_session_path", return_value="/tmp/sophia-test/tiss"),
        ):
            settings, creds = require_tiss_session()

        assert settings is mock_settings
        assert creds is mock_creds

    def test_returns_none_when_no_session(self) -> None:
        from unittest.mock import MagicMock

        from sophia.cli._output import require_tiss_session

        mock_settings = MagicMock()
        mock_settings.config_dir = "/tmp/sophia-test"

        with (
            patch("sophia.config.Settings", return_value=mock_settings),
            patch("sophia.adapters.auth.load_tiss_session", return_value=None),
            patch("sophia.adapters.auth.tiss_session_path", return_value="/tmp/sophia-test/tiss"),
        ):
            settings, creds = require_tiss_session()

        assert settings is mock_settings
        assert creds is None
