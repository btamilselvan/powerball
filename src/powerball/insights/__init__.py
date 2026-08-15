"""LLM-generated commentary over historical draw stats.

`llm.py` is the pluggable backend (Ollama/OpenAI-compatible) that talks HTTP directly to a model
server; `insights.py` turns `draws.stats` output into a compact digest, sends it through `llm.py`,
and validates the structured result. Descriptive/novelty output layered on real historical data —
never a predictive edge; see `insights.py`'s module docstring for specifics.
"""
