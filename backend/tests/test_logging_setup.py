import logging

from app.logs import configure_logging


def test_the_apps_loggers_write_info_lines_and_setting_up_twice_adds_nothing():
    log = logging.getLogger("memoryatlas")
    configure_logging()
    configure_logging()
    ours = [h for h in log.handlers if getattr(h, "_memoryatlas", False)]
    assert len(ours) == 1
    assert log.level == logging.INFO
    assert logging.getLogger("memoryatlas.llm").getEffectiveLevel() == logging.INFO
