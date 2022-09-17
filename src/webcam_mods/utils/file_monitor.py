from pathlib import Path
from loguru import logger
from inotify_simple import INotify, flags


class MonitorFile:
    """
    track how many processses are using a file/device
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        self.consumers = 0

    def setup(self):
        self.consumers = 0
        inotify = INotify(nonblocking=True)
        self.inotify = inotify
        watch_flags = (
            flags.CREATE | flags.OPEN | flags.CLOSE_NOWRITE | flags.CLOSE_WRITE
        )
        inotify.add_watch(self.path.absolute(), watch_flags)

    def _check_inotify(self):
        for event in self.inotify.read(0):
            for flag in flags.from_mask(event.mask):
                if flag == flags.CLOSE_NOWRITE or flag == flags.CLOSE_WRITE:
                    self.consumers = max(0, self.consumers - 1)
                if flag == flags.OPEN:
                    self.consumers += 1
                logger.debug(f"Consumers: {self.consumers}")

    def teardown(self):
        self.consumers = 0
        self.inotify.close()

    def is_in_use(self) -> bool:
        self._check_inotify()
        return self.consumers > 0
