"""对话提单图。会话状态以 draft 表为准，每轮从数据库载入草稿后执行一次图，不使用 checkpointer。"""
from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    ChatState,
    extract,
    link_contract,
    merge,
    normalize_material,
    respond,
    respond_help,
    route_after_extract,
)


@lru_cache
def build_graph():
    g = StateGraph(ChatState)
    g.add_node("extract", extract)
    g.add_node("merge", merge)
    g.add_node("normalize_material", normalize_material)
    g.add_node("link_contract", link_contract)
    g.add_node("respond", respond)
    g.add_node("help", respond_help)
    g.add_edge(START, "extract")
    g.add_conditional_edges("extract", route_after_extract, {"help": "help", "merge": "merge"})
    g.add_edge("merge", "normalize_material")
    g.add_edge("normalize_material", "link_contract")
    g.add_edge("link_contract", "respond")
    g.add_edge("respond", END)
    g.add_edge("help", END)
    return g.compile()
