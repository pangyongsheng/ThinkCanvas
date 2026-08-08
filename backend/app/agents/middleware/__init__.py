"""``app.agents.middleware`` — LangChain AgentMiddleware 实现。

这里只放对框架原生钩子的薄封装；持久化落库交给 DAO，
中间件不做 SQL。
"""
from app.agents.middleware.persistence import AgentPersistenceMiddleware

__all__ = ["AgentPersistenceMiddleware"]
