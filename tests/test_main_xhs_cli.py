from pathlib import Path
from unittest.mock import patch

from src.main import main


def test_collect_xhs_cli_defaults_target_recent_important_results():
    with patch("src.ingest.xhs_collector.collect_xhs", return_value=Path("xhs.jsonl")) as collect:
        assert main(["--collect-xhs", "kw"]) == 0

    collect.assert_called_once_with(
        "kw",
        filters={"sort_by": "最多评论", "publish_time": "一天内"},
        max_items=None,
    )


def test_collect_xhs_cli_explicit_filters_are_preserved():
    with patch("src.ingest.xhs_collector.collect_xhs", return_value=Path("xhs.jsonl")) as collect:
        assert main([
            "--collect-xhs", "kw",
            "--xhs-sort-by", "最新",
            "--xhs-publish-time", "一周内",
            "--xhs-note-type", "视频",
            "--xhs-max-items", "3",
        ]) == 0

    collect.assert_called_once_with(
        "kw",
        filters={"sort_by": "最新", "publish_time": "一周内", "note_type": "视频"},
        max_items=3,
    )
