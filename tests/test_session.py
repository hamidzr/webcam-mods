import json
import os
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np

from webcam_mods.session import Command, RunSession
from webcam_mods.utils.cli_input import StdinControls
from webcam_mods.utils.config import Config


class SessionTests(unittest.TestCase):
    def session(self, **kwargs):
        return RunSession(Config(path=None, width=20, height=20), **kwargs)

    def test_ordered_controls_apply_between_frames(self):
        session = self.session()
        self.assertTrue(session.submit(Command("resize", -10, -10)))
        self.assertTrue(session.submit(Command("move", 4, 2)))
        self.assertTrue(session.submit(Command("pad", 2, 2)))
        self.assertEqual(session.settings.crop_dims, [20, 20])
        self.assertTrue(all(result.applied for result in session.apply_commands()))
        self.assertEqual(session.settings.crop_dims, [10, 10])
        self.assertEqual(session.settings.crop_pos, [4, 2])
        self.assertEqual(session.settings.pad_size, [2, 2])
        result = session.prepare(np.full((20, 20, 3), 90, dtype=np.uint8))
        self.assertEqual(result.shape, (10, 10, 3))
        self.assertTrue(np.all(result[0] == 0))
        self.assertTrue(np.all(result[2:-2, 2:-2] == 90))

    def test_invalid_mutation_preserves_settings(self):
        session = self.session()
        initial = session.settings.to_dict()
        session.submit(Command("pad", 20, 0))
        session.submit(Command("resize", -20, 0))
        self.assertFalse(any(result.applied for result in session.apply_commands()))
        self.assertEqual(session.settings.to_dict(), initial)

    def test_replay_empty_and_new_recording(self):
        session = self.session()
        session.submit(Command("replay"))
        self.assertFalse(session.apply_commands()[0].applied)
        for value in (10, 20):
            if value == 10:
                session.submit(Command("record"))
                session.apply_commands()
            session.prepare(np.full((20, 20, 3), value, np.uint8))
        session.submit(Command("replay"))
        session.apply_commands()
        frame = np.zeros((20, 20, 3), np.uint8)
        self.assertEqual(int(session.prepare(frame)[0, 0, 0]), 10)
        self.assertEqual(int(session.prepare(frame)[0, 0, 0]), 20)
        session.submit(Command("record"))
        session.apply_commands()
        session.prepare(np.full_like(frame, 30))
        session.submit(Command("replay"))
        session.apply_commands()
        self.assertEqual(int(session.prepare(frame)[0, 0, 0]), 30)

    def test_recording_limit_copies_and_session_isolation(self):
        session = self.session(recording_limit=1200)
        other = self.session()
        frame = np.full((20, 20, 3), 50, np.uint8)
        session.submit(Command("record"))
        session.apply_commands()
        session.prepare(frame)
        frame[:] = 0
        session.prepare(frame)
        self.assertFalse(session.recorder.recording)
        self.assertEqual(session.recorder.size_bytes, 1200)
        self.assertTrue(np.all(session.recorder.frames[0] == 50))
        self.assertEqual(other.recorder.frames, [])
        session.close()
        self.assertFalse(session.submit(Command("record")))
        self.assertEqual(session.recorder.frames, [])

    def test_config_validation_and_atomic_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            config = Config(path, width=20, height=20)
            self.assertFalse(path.exists(), "construction must not write defaults")
            path.write_text('{"crop_dims": "bad"}')
            self.assertEqual(Config(path, width=20, height=20).crop_dims, [20, 20])
            session = RunSession(config)
            session.submit(Command("resize", -10, -10))
            session.apply_commands()
            self.assertEqual(json.loads(path.read_text())["crop_dims"], [10, 10])
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_stdin_queue_preserves_commands_and_stops(self):
        session = self.session()
        read_fd, write_fd = os.pipe()
        with os.fdopen(read_fd) as stream:
            controls = StdinControls(session.submit, stream)
            try:
                controls.start()
                os.write(write_fd, b"record\nstop\nreplay\n")
                deadline = time.monotonic() + 2
                while session.commands.qsize() < 3 and time.monotonic() < deadline:
                    time.sleep(0.01)
                results = session.apply_commands()
                self.assertEqual(
                    [r.command.action for r in results], ["record", "stop", "replay"]
                )
                self.assertFalse(results[-1].applied)
                thread = controls._thread
                controls.stop()
                self.assertFalse(thread.is_alive())
            finally:
                controls.stop()
                os.close(write_fd)
