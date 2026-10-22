import shiboken6

from torrentlinker.catalogue import CrawlProgress
from torrentlinker.gui.catalogue_runner import CatalogueRunner


def test_a_fetch_still_running_when_the_window_is_gone_ends_quietly(qapp) -> None:  # type: ignore[no-untyped-def]
    pages: list[int] = []

    def work(stop, progress) -> None:  # type: ignore[no-untyped-def]
        for page in range(1, 10):
            if stop():
                return
            pages.append(page)
            progress(CrawlProgress(2030, page, 0, page * 100))

    runner = CatalogueRunner(work)
    shiboken6.delete(runner.signals)  # what closing the app does to it

    runner.run()  # must not raise

    assert pages == [1]  # and it stops instead of fetching on for nobody


def test_a_work_error_is_reported_while_the_gui_is_alive(qapp) -> None:  # type: ignore[no-untyped-def]
    error = RuntimeError("fetch failed")

    def work(stop, progress) -> None:  # type: ignore[no-untyped-def]
        raise error

    runner = CatalogueRunner(work)
    failed: list[Exception] = []
    finished: list[bool] = []
    runner.signals.failed.connect(failed.append)
    runner.signals.finished.connect(finished.append)

    runner.run()

    assert failed == [error]
    assert finished == [False]


def test_a_work_error_after_the_gui_is_destroyed_ends_quietly(qapp) -> None:  # type: ignore[no-untyped-def]
    def work(stop, progress) -> None:  # type: ignore[no-untyped-def]
        raise ValueError("fetch failed")

    runner = CatalogueRunner(work)
    shiboken6.delete(runner.signals)

    runner.run()

    assert runner.stopped
