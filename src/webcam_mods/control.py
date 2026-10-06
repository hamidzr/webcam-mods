"""Local JSONL control worker. Stdout contains protocol messages only."""

from importlib.metadata import version
import json
import sys
import threading
from typing import Any, Callable

from webcam_mods.profiles import Profile, ProfileStore
from webcam_mods.input.input import FrameInput
from webcam_mods.settings import StartupSettings


def run_profile(
    profile: Profile,
    stop: threading.Event,
    ready: Callable[[], None],
    source_ready: Callable[[FrameInput], None],
) -> None:
    from webcam_mods.capture import create_camera
    from webcam_mods.effects import ProfileEffect
    from webcam_mods.frame_producer import WorkerShutdownTimeout
    from webcam_mods.loopback import live_loop

    settings = StartupSettings(
        in_width=profile.width,
        in_height=profile.height,
        out_width=profile.width,
        out_height=profile.height,
        in_fps=profile.fps,
        max_out_fps=profile.fps,
        video_in=profile.input_device,
        repeat_frames=profile.repeat_frames,
        processing_fps=profile.processing_fps,
    )
    effect = ProfileEffect(profile, settings)
    transferred = False
    closed = False
    try:
        source = create_camera(settings, profile.capture)  # type: ignore[arg-type]
        source_ready(source)
        if stop.is_set():
            return
        transferred = True
        live_loop(
            mod=effect,
            fIn=source,
            interactive_listener=None,
            settings=settings,
            processing_cleanup=effect.close,
            should_stop=stop.is_set,
            on_ready=ready,
            strict_errors=True,
        )
    except WorkerShutdownTimeout:
        # backend process must exit; it cannot safely start another session
        raise
    except BaseException:
        effect.close()
        closed = True
        raise
    finally:
        if not transferred and not closed:
            effect.close()


class Controller:
    def __init__(
        self,
        store: ProfileStore,
        emit: Callable[[dict[str, Any]], None],
        runner: Callable[
            [
                Profile,
                threading.Event,
                Callable[[], None],
                Callable[[FrameInput], None],
            ],
            None,
        ] = run_profile,
    ) -> None:
        self.store, self.emit, self.runner = store, emit, runner
        self.lock = threading.RLock()
        self.state = "idle"
        self.error: str | None = None
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.source: FrameInput | None = None
        self.poisoned = False

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "state": self.state,
                **({"error": self.error} if self.error else {}),
            }

    def _state(self, state: str, error: str | None = None) -> None:
        with self.lock:
            self.state, self.error = state, error
            self.emit({"event": "status", "data": self.status()})

    def start(self, profile: Profile) -> dict[str, Any]:
        with self.lock:
            if self.poisoned:
                raise RuntimeError(
                    "worker shutdown timed out; restart the control worker"
                )
            if self.thread is not None and self.thread.is_alive():
                raise RuntimeError(
                    "session already active; stop it before starting another"
                )
            self.stop_event = threading.Event()
            self.source = None
            self._state("starting")

            def source_ready(source: FrameInput) -> None:
                with self.lock:
                    self.source = source
                    if self.stop_event.is_set():
                        source.request_stop()

            def ready() -> None:
                with self.lock:
                    if not self.stop_event.is_set() and self.state == "starting":
                        self._state("running")

            def run() -> None:
                try:
                    self.runner(profile, self.stop_event, ready, source_ready)
                except Exception as error:
                    from webcam_mods.frame_producer import WorkerShutdownTimeout

                    if isinstance(error, WorkerShutdownTimeout):
                        self.poisoned = True
                    self._state("error", str(error))
                else:
                    self._state("idle")
                finally:
                    with self.lock:
                        self.source = None

            self.thread = threading.Thread(
                target=run, name="webcam-session", daemon=True
            )
            self.thread.start()
            return self.status()

    def stop(self) -> dict[str, Any]:
        with self.lock:
            thread = self.thread
            if thread is None or not thread.is_alive():
                return self.status()
            self._state("stopping")
            self.stop_event.set()
            source = self.source
        cancellation_error = None
        if source is not None:
            try:
                source.request_stop()
            except Exception as error:
                cancellation_error = str(error)
        thread.join(timeout=12)
        if thread.is_alive():
            self.poisoned = True
            self._state("error", "session stop timed out; restart the control worker")
        elif cancellation_error is not None:
            self._state("error", cancellation_error)
        return self.status()

    def dispatch(self, method: object, params: object) -> Any:
        if not isinstance(params, dict):
            raise ValueError("params must be an object")
        if method == "hello":
            return {"protocol": 1, "version": version("webcam-mods")}
        if method == "status":
            return self.status()
        if method == "profiles.list":
            return self.store.list()
        if method == "profiles.save":
            self.store.save(params.get("name"), params.get("config"))
            return True
        if method == "profiles.delete":
            self.store.delete(params.get("name"))
            return True
        if method == "cameras.list":
            if sys.platform != "darwin":
                raise RuntimeError("camera inventory requires macOS")
            from webcam_mods.macos.capture import camera_inventory

            capture = params.get("capture", "avfoundation")
            if capture not in ("auto", "opencv", "avfoundation"):
                raise ValueError("invalid capture backend")
            return [
                {"index": camera.input_index, "name": camera.name}
                for camera in camera_inventory(capture)
                if not camera.excluded_reason
            ]
        if method == "start":
            profile = (
                self.store.get(params["profile"])
                if "profile" in params
                else Profile.parse(params.get("config", {}))
            )
            return self.start(profile)
        if method in ("stop", "shutdown"):
            return self.stop()
        raise ValueError("unknown method")


def main() -> None:
    from loguru import logger

    logger.remove()
    logger.add(sys.stderr)
    output_lock = threading.Lock()
    output_closed = threading.Event()
    controller: Controller | None = None

    def emit(message: dict[str, Any]) -> None:
        with output_lock:
            if output_closed.is_set():
                return
            try:
                print(json.dumps(message, allow_nan=False), flush=True)
            except BrokenPipeError, OSError:
                output_closed.set()
                if controller is not None:
                    controller.stop_event.set()
                    source = controller.source
                    if source is not None:
                        try:
                            source.request_stop()
                        except Exception:
                            pass

    controller = Controller(ProfileStore(), emit)
    try:
        for line in sys.stdin:
            if output_closed.is_set():
                break
            request: Any = None
            try:
                request = json.loads(line)
                if not isinstance(request, dict) or "id" not in request:
                    raise ValueError("request must be an object with id")
                result = controller.dispatch(
                    request.get("method"), request.get("params", {})
                )
                emit({"id": request["id"], "result": result})
                if request.get("method") == "shutdown":
                    break
            except Exception as error:
                emit(
                    {
                        "id": request.get("id") if isinstance(request, dict) else None,
                        "error": str(error),
                    }
                )
    finally:
        controller.stop()


if __name__ == "__main__":
    main()
