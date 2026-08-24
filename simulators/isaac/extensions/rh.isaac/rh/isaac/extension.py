"""Kit lifecycle entry point for the PR 13 Isaac backend skeleton."""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress

import carb
import omni.ext
import omni.kit.app
import omni.timeline
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from rh_interfaces.msg import ComponentStatus

from .clock_graph import ensure_clock_graph

_COMPONENT_ID = "isaac_env"
_STATUS_TOPIC = "/roboharness/env/status"
_INITIALIZATION_ERROR = 1301


def _status_qos() -> QoSProfile:
    return QoSProfile(
        history=HistoryPolicy.KEEP_LAST,
        depth=1,
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.TRANSIENT_LOCAL,
    )


class _StatusPublisher:
    """Minimal Env status publisher; reusable protocol helpers stay outside Kit."""

    def __init__(self, node: Node) -> None:
        self._node = node
        self._publisher = node.create_publisher(
            ComponentStatus,
            _STATUS_TOPIC,
            _status_qos(),
        )
        self._message = ComponentStatus()
        self.transition(ComponentStatus.STARTING)

    def transition(
        self,
        state: int,
        *,
        error_code: int = 0,
        detail: str = "",
        restart_required: bool = False,
    ) -> None:
        self._message.stamp = self._node.get_clock().now().to_msg()
        self._message.component_id = _COMPONENT_ID
        self._message.state = state
        self._message.error_code = error_code
        self._message.detail = detail
        self._message.restart_required = restart_required
        self.publish()

    def publish(self) -> None:
        self._publisher.publish(self._message)


class Extension(omni.ext.IExt):
    """Start the Bridge smoke graph without claiming a complete Env READY state."""

    def on_startup(self, ext_id: str) -> None:
        self._ext_id = ext_id
        self._node = None
        self._status = None
        self._owns_rclpy = False
        self._next_heartbeat = time.monotonic()
        self._init_task = None
        self._spin_task = None
        self._simulation_context = None
        self._app_ready_sub = None
        self._graph_initialized = False
        carb.log_info("[rh.isaac] STARTING Isaac backend and native ROS 2 Bridge")
        try:
            self._start_status_publisher()
        except Exception as exc:
            carb.log_error(f"[rh.isaac] status publisher failed: {exc!r}")
            return

        app = omni.kit.app.get_app()
        if app.is_app_ready():
            self._on_app_ready(None)
            return
        self._app_ready_sub = (
            app.get_startup_event_stream().create_subscription_to_pop_by_type(
                omni.kit.app.EVENT_APP_READY,
                self._on_app_ready,
                name="rh.isaac initialize Bridge graph",
            )
        )
        if app.is_app_ready():
            self._on_app_ready(None)

    def _on_app_ready(self, _event) -> None:
        self._app_ready_sub = None
        if self._graph_initialized:
            return
        self._graph_initialized = True
        self._init_task = asyncio.ensure_future(self._initialize_backend())

    async def _initialize_backend(self) -> None:
        try:
            if omni.usd.get_context().get_stage() is None:
                raise RuntimeError("USD stage is unavailable after Kit app ready")

            # In an extension workflow Kit owns the render/update loop, while
            # SimulationContext owns Isaac's physics/timeline lifecycle.
            from isaacsim.core.api import SimulationContext

            self._simulation_context = SimulationContext(
                physics_dt=1.0 / 60.0,
                rendering_dt=1.0 / 60.0,
            )
            await self._simulation_context.initialize_simulation_context_async()
            graph_path = ensure_clock_graph()
            await self._simulation_context.play_async()
            self._status.transition(
                ComponentStatus.STARTING,
                detail="native ROS 2 Bridge clock smoke active; full READY deferred to PR 16",
            )
            self._spin_task = asyncio.ensure_future(self._spin_status())
            carb.log_info(f"[rh.isaac] clock graph active at {graph_path}")
        except Exception as exc:
            carb.log_error(f"[rh.isaac] initialization failed: {exc!r}")
            if self._status is not None:
                self._status.transition(
                    ComponentStatus.ERROR,
                    error_code=_INITIALIZATION_ERROR,
                    detail=str(exc),
                    restart_required=True,
                )

    def _start_status_publisher(self) -> None:
        if not rclpy.ok():
            rclpy.init(args=None)
            self._owns_rclpy = True
        self._node = rclpy.create_node("rh_isaac_backend")
        self._status = _StatusPublisher(self._node)

    async def _spin_status(self) -> None:
        try:
            while self._node is not None and rclpy.ok():
                rclpy.spin_once(self._node, timeout_sec=0.0)
                now = time.monotonic()
                if now >= self._next_heartbeat:
                    self._status.publish()
                    self._next_heartbeat = now + 1.0
                await omni.kit.app.get_app().next_update_async()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            carb.log_error(f"[rh.isaac] clock/status loop failed: {exc!r}")
            if self._status is not None:
                self._status.transition(
                    ComponentStatus.ERROR,
                    error_code=_INITIALIZATION_ERROR,
                    detail=str(exc),
                    restart_required=True,
                )

    def on_shutdown(self) -> None:
        omni.timeline.get_timeline_interface().stop()
        self._app_ready_sub = None
        if self._init_task is not None and not self._init_task.done():
            self._init_task.cancel()
        if self._spin_task is not None and not self._spin_task.done():
            self._spin_task.cancel()
        if self._simulation_context is not None:
            with suppress(Exception):
                type(self._simulation_context).clear_instance()
            self._simulation_context = None
        if self._node is not None:
            with suppress(Exception):
                self._node.destroy_node()
            self._node = None
        if self._owns_rclpy and rclpy.ok():
            with suppress(Exception):
                rclpy.shutdown()
        carb.log_info("[rh.isaac] extension stopped")
