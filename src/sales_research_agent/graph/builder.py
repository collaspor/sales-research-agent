"""可恢复 POC LangGraph 的装配入口。"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from sales_research_agent.domain.models import ResearchQuestion, RunStats
from sales_research_agent.domain.repository import DomainRepository
from sales_research_agent.graph.nodes import make_nodes
from sales_research_agent.graph.state import PocState
from sales_research_agent.infrastructure.artifacts import ArtifactStore
from sales_research_agent.providers.base import ResearchModel, SearchProvider
from sales_research_agent.sources.authority import SourceAuthorityPolicy


@dataclass(slots=True)
class Services:
    """Graph 闭包所需的基础设施；禁止将客户端放入状态。"""

    repository: DomainRepository
    artifacts: ArtifactStore
    search: SearchProvider
    model: ResearchModel
    fetcher: Any
    clock: Callable[[], datetime]
    max_sources: int = 6
    max_questions: int = 4
    crash_once: bool = False
    questions: dict[str, ResearchQuestion] = field(default_factory=dict)
    run_stats_type: type[RunStats] = RunStats
    source_policy: SourceAuthorityPolicy = field(default_factory=SourceAuthorityPolicy)


def build_poc_graph(services: Services, checkpointer: Any) -> Any:
    """构建具有动态来源 fan-out 和单次汇聚发布的状态图。"""
    nodes = make_nodes(services)
    graph = StateGraph(PocState)
    graph.add_node("plan_research", nodes["plan_research"])
    graph.add_node("discover_sources", nodes["discover_sources"])
    graph.add_node("ingest_source", nodes["ingest_source"])
    graph.add_node("publish_report", nodes["publish_report"])
    graph.add_edge(START, "plan_research")
    graph.add_edge("plan_research", "discover_sources")
    graph.add_conditional_edges("discover_sources", _fan_out_sources)
    graph.add_edge("ingest_source", "publish_report")
    graph.add_edge("publish_report", END)
    return graph.compile(checkpointer=checkpointer)


def _fan_out_sources(state: PocState) -> list[Send]:
    """每条 Send 仅传递局部来源输入，避免复制全局状态。"""
    return [
        Send(
            "ingest_source",
            {"run_id": state["run_id"], "current_source_id": source_id,
             "deadline_at": state["deadline_at"]},
        )
        for source_id in state["source_ids"]
    ]
