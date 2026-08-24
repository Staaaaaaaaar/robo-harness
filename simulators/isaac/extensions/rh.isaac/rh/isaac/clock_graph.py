"""Native Isaac Sim ROS 2 Bridge graph construction."""

from __future__ import annotations

CLOCK_GRAPH_PATH = "/RoboHarness/ROS2Clock"


def ensure_clock_graph() -> str:
    """Create the idempotent simulation-clock publishing Action Graph."""

    import omni.graph.core as og
    import omni.usd

    stage = omni.usd.get_context().get_stage()
    if stage is None:
        raise RuntimeError("USD stage is unavailable")
    if stage.GetPrimAtPath(CLOCK_GRAPH_PATH).IsValid():
        return CLOCK_GRAPH_PATH

    keys = og.Controller.Keys
    og.Controller.edit(
        {
            "graph_path": CLOCK_GRAPH_PATH,
            "evaluator_name": "execution",
            "pipeline_stage": og.GraphPipelineStage.GRAPH_PIPELINE_STAGE_SIMULATION,
        },
        {
            keys.CREATE_NODES: [
                ("OnPlaybackTick", "omni.graph.action.OnPlaybackTick"),
                ("RosContext", "isaacsim.ros2.bridge.ROS2Context"),
                ("ReadSimulationTime", "isaacsim.core.nodes.IsaacReadSimulationTime"),
                ("PublishClock", "isaacsim.ros2.bridge.ROS2PublishClock"),
            ],
            keys.CONNECT: [
                ("OnPlaybackTick.outputs:tick", "PublishClock.inputs:execIn"),
                ("RosContext.outputs:context", "PublishClock.inputs:context"),
                (
                    "ReadSimulationTime.outputs:simulationTime",
                    "PublishClock.inputs:timeStamp",
                ),
            ],
        },
    )
    return CLOCK_GRAPH_PATH
