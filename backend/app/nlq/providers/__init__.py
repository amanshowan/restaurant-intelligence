"""Provider adapters.

Exactly one module here may import a vendor SDK. Everything else in the
application depends on `app.nlq.llm.LLMClient`, so adding a second provider
means adding a file beside this one and a branch in `build_llm_client` — not
touching the planner, the orchestrator or the endpoint.
"""

from app.nlq.providers.factory import build_llm_client

__all__ = ["build_llm_client"]
