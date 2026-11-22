from enum import StrEnum


class ProfileSource(StrEnum):
    RULE_BASED = "rule_based"  # Phase 1: industry catalog heuristics
    AI = "ai"  # Phase 2: Qwen/DeepSeek agents
    MANUAL = "manual"  # operator or customer edits
