"""Local JSONL control worker. Stdout contains protocol messages only."""

from importlib.metadata import version
import json
import sys
import threading
from typing import TYPE_CHECKING, Any, Callable

from webcam_mods.profiles import RESTART_FIELDS, Profile, ProfileStore
from webcam_mods.protocol import RequestFailure, read_requests
from webcam_mods.output.native_preview import VIEWS, NativePreview
from webcam_mods.stats import RateMeter
from webcam_mods.utils.video import Frame

_STOP_TIMEOUT = 12
from webcam_mods.input.input import AdapterMetadata, FrameInput
from webcam_mods.settings import StartupSettings

if TYPE_CHECKING:
    from webcam_mods.effects import PreviewSink, ProfileEffect


def run_profile(
    profile: Profile,
    stop: threading.Event,
    ready: Callable[[], None],
    source_ready: Callable[[FrameInput], None],
    *,
    output: str = "virtualcam",
    on_frame: Callable[[Frame], None] | None = None,
    on_output_ready: Callable[[AdapterMetadata], None] | None = None,
    on_effect: Callable[["ProfileEffect"], None] | None = None,
    on_warning: Callable[[str], None] | None = None,
    preview: "PreviewSink | None" = None,
    should_pause: Callable[[], bool] | None = None,
) -> None:
    from webcam_mods.capture import camera_index_for_id, create_camera
    from webcam_mods.effects import ProfileEffect
    from webcam_mods.frame_producer import WorkerShutdownTimeout
    from webcam_mods.loopback import live_loop

    if output not in ("virtualcam", "preview"):
        raise ValueError("output must be virtualcam or preview")
    input_device = (
        camera_index_for_id(profile.camera_id, profile.capture)  # type: ignore[arg-type]
        if profile.camera_id is not None
        else profile.input_device
    )
    oriented_width, oriented_height = profile.oriented_size
    settings = StartupSettings(
        in_width=profile.width,
        in_height=profile.height,
        out_width=profile.output_width or oriented_width,
        out_height=profile.output_height or oriented_height,
        in_fps=profile.fps,
        max_out_fps=profile.output_fps or profile.fps,
        video_in=input_device,
        repeat_frames=profile.repeat_frames,
        processing_fps=profile.processing_fps,
        signal_pattern=profile.signal_pattern,  # type: ignore[arg-type]
    )
    # the effect owns orientation; flips change while running, rotation restarts
    effect = ProfileEffect(profile, settings, on_warning=on_warning, preview=preview)
    if on_effect is not None:
        on_effect(effect)
    transferred = False
    closed = False
    try:
        source = create_camera(
            settings, profile.capture, device_id=profile.camera_id  # type: ignore[arg-type]
        )
        source_ready(source)
        if stop.is_set():
            return
        transferred = True
        live_loop(
            mod=effect,
            fIn=source,
            output_backend="native-preview" if output == "preview" else "virtual-cam",
            interactive_listener=None,
            settings=settings,
            processing_cleanup=effect.close,
            should_stop=stop.is_set,
            on_ready=ready,
            strict_errors=True,
            on_frame=on_frame,
            on_output_ready=on_output_ready,
            should_pause=should_pause,
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
        runner: (
            Callable[
                [
                    Profile,
                    threading.Event,
                    Callable[[], None],
                    Callable[[FrameInput], None],
                ],
                None,
            ]
            | None
        ) = None,
    ) -> None:
        self.store, self.emit = store, emit
        self.runner = run_profile if runner is None else runner
        self._native_runner = run_profile if runner is None else None
        self.lock = threading.RLock()
        self.state = "idle"
        self.error: str | None = None
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.source: FrameInput | None = None
        self.poisoned = False
        self.preview: NativePreview | None = None
        self.output_fps: float | None = None
        self.profile: Profile | None = None
        self.effect: ProfileEffect | None = None
        self.sent = RateMeter()
        # user pause: capture closes and output shows the loading picture
        self.paused = threading.Event()

    def _clear_preview(self) -> None:
        self.output_fps = None
        self.effect = None
        if self.preview is not None:
            self.preview.close()
            self.preview = None

    def status(self) -> dict[str, Any]:
        with self.lock:
            return {
                "state": self.state,
                **({"error": self.error} if self.error else {}),
                **({"restart_required": True} if self.poisoned else {}),
                **(
                    {"output_fps": self.output_fps}
                    if self.output_fps is not None
                    else {}
                ),
                **(
                    {"paused": True}
                    if self.paused.is_set() and self.state == "running"
                    else {}
                ),
            }

    def _state(self, state: str, error: str | None = None) -> None:
        with self.lock:
            if self.poisoned:
                return
            self.state, self.error = state, error
            if state in ("idle", "error", "stopping"):
                self._clear_preview()
            self.emit({"event": "status", "data": self.status()})

    def _poison(self, error: str) -> None:
        with self.lock:
            if self.poisoned:
                return
            self.poisoned = True
            self._clear_preview()
            self.state = "error"
            self.error = (
                f"{error}; quit and reopen the app or restart the control worker"
            )
            self.emit({"event": "status", "data": self.status()})

    def start(self, profile: Profile, output: str = "virtualcam") -> dict[str, Any]:
        if output not in ("virtualcam", "preview"):
            raise ValueError("output must be virtualcam or preview")
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
            self._clear_preview()
            preview = self.preview = NativePreview()
            sent = self.sent = RateMeter()
            paused = self.paused = threading.Event()
            self.profile = profile
            self._state("starting")

            def effect_ready(effect: ProfileEffect) -> None:
                with self.lock:
                    if self.preview is preview and not self.stop_event.is_set():
                        self.effect = effect

            def warning(message: str) -> None:
                self.emit({"event": "warning", "data": {"message": message}})

            def source_ready(source: FrameInput) -> None:
                with self.lock:
                    self.source = source
                    if self.stop_event.is_set():
                        source.request_stop()

            def ready() -> None:
                with self.lock:
                    if not self.stop_event.is_set() and self.state == "starting":
                        self._state("running")

            def deliver(frame: Frame) -> None:
                sent.tick()
                preview.publish(frame)

            def output_ready(metadata: AdapterMetadata) -> None:
                with self.lock:
                    if (
                        self.preview is preview
                        and not self.stop_event.is_set()
                        and self.state == "starting"
                    ):
                        self.output_fps = metadata["fps"]
                        self.emit({"event": "status", "data": self.status()})

            def run() -> None:
                try:
                    if self._native_runner is not None:
                        self._native_runner(
                            profile,
                            self.stop_event,
                            ready,
                            source_ready,
                            output=output,
                            on_frame=deliver,
                            on_output_ready=output_ready,
                            on_effect=effect_ready,
                            on_warning=warning,
                            preview=preview,
                            should_pause=paused.is_set,
                        )
                    else:
                        self.runner(profile, self.stop_event, ready, source_ready)
                except Exception as error:
                    from webcam_mods.frame_producer import WorkerShutdownTimeout

                    if isinstance(error, WorkerShutdownTimeout):
                        self._poison(str(error))
                    else:
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

    def update(self, profile: Profile) -> dict[str, Any]:
        """Apply live settings to the running session without reopening devices."""
        with self.lock:
            effect, running = self.effect, self.profile
            if (
                self.state not in ("starting", "running")
                or effect is None
                or running is None
            ):
                raise RuntimeError("no running session to update")
            changed = sorted(
                name
                for name in RESTART_FIELDS
                if getattr(profile, name) != getattr(running, name)
            )
            if changed:
                raise ValueError(f"restart required to change {', '.join(changed)}")
            effect.update(profile)
            self.profile = profile
            return self.status()

    def pause(self, paused: bool) -> dict[str, Any]:
        """Pause or resume the running session's video; output stays open."""
        with self.lock:
            if self.state != "running":
                raise RuntimeError("camera is not running")
            if paused != self.paused.is_set():
                if paused:
                    self.paused.set()
                else:
                    self.paused.clear()
                self.emit({"event": "status", "data": self.status()})
            return self.status()

    def stats(self) -> dict[str, float | None] | None:
        """Processed and sent frame rates plus mean effect time, or None when idle."""
        with self.lock:
            effect, sent = self.effect, self.sent
            if self.state not in ("starting", "running") or effect is None:
                return None
        processed_fps, effect_seconds = effect.stats.snapshot()
        sent_fps, _ = sent.snapshot()

        def rounded(value: float | None, digits: int = 1) -> float | None:
            return None if value is None else round(value, digits)

        return {
            "processed_fps": rounded(processed_fps),
            "sent_fps": rounded(sent_fps),
            "effect_ms": rounded(
                None if effect_seconds is None else effect_seconds * 1000
            ),
        }

    def white_balance(self, x: float, y: float) -> dict[str, int]:
        """Neutral temperature and tint for a camera point; the app applies them."""
        with self.lock:
            effect = self.effect
            if self.state not in ("starting", "running") or effect is None:
                raise RuntimeError("no running session")
        temperature, tint = effect.white_balance(x, y)
        return {"temperature": temperature, "tint": tint}

    def stop(self) -> dict[str, Any]:
        with self.lock:
            thread = self.thread
            if thread is None or not thread.is_alive():
                self._clear_preview()
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
        thread.join(timeout=_STOP_TIMEOUT)
        if thread.is_alive():
            self._poison("session stop timed out")
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
        if method == "preview.get":
            if set(params) - {"view"}:
                raise ValueError("preview.get accepts only view")
            view = params.get("view", "output")
            if view not in VIEWS:
                raise ValueError(f"view must be one of {', '.join(VIEWS)}")
            with self.lock:
                return self.preview.get(view) if self.preview is not None else None
        if method == "session.stats":
            if params:
                raise ValueError("session.stats params must be empty")
            return self.stats()
        if method == "session.pause":
            if set(params) != {"paused"} or not isinstance(params["paused"], bool):
                raise ValueError("session.pause needs paused true or false")
            return self.pause(params["paused"])
        if method == "session.white_balance":
            if set(params) != {"x", "y"} or not all(
                isinstance(params[key], (int, float))
                and not isinstance(params[key], bool)
                and 0 <= params[key] <= 1
                for key in ("x", "y")
            ):
                raise ValueError("session.white_balance needs x and y in 0..1")
            return self.white_balance(params["x"], params["y"])
        if method == "profiles.list":
            return self.store.list()
        if method == "profiles.seed_defaults":
            if params:
                raise ValueError("profiles.seed_defaults params must be empty")
            self.store.seed_defaults()
            return True
        if method == "profiles.errors":
            return self.store.errors()
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
                {
                    "index": camera.input_index,
                    "name": camera.name,
                    "id": camera.device_id,
                }
                for camera in camera_inventory(capture)
                if not camera.excluded_reason
            ]
        if method == "start":
            profile = (
                self.store.get(params["profile"])
                if "profile" in params
                else Profile.parse(params.get("config", {}))
            )
            return self.start(profile, params.get("output", "virtualcam"))
        if method == "session.update":
            if set(params) != {"config"}:
                raise ValueError("session.update requires only config")
            return self.update(Profile.parse(params["config"]))
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
        for request in read_requests(sys.stdin):
            if output_closed.is_set():
                break
            if isinstance(request, RequestFailure):
                emit({"id": request.id, "error": request.error})
                continue
            try:
                result = controller.dispatch(request.method, request.params)
                emit({"id": request.id, "result": result})
                if request.method == "shutdown":
                    break
            except Exception as error:
                emit({"id": request.id, "error": str(error)})
    finally:
        controller.stop()


if __name__ == "__main__":
    main()
