"""
Vallen — LLM Opponent.
Implements AI decision making using Large Language Models.
"""

import os
import json
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class LLMProvider(ABC):
    @abstractmethod
    def get_action(self, prompt: str) -> str:
        """Returns the raw string response from the LLM."""
        pass

class AnthropicProvider(LLMProvider):
    def __init__(self):
        self.api_key = os.environ.get("VALLEN_LLM_API_KEY")
        if not self.api_key:
            raise ValueError("VALLEN_LLM_API_KEY not set")

    def get_action(self, prompt: str) -> str:
        # Actual implementation would use anthropic python SDK
        # return client.messages.create(...)
        return '{"action": "end_phase"}' # Mock for now

class OpenAIProvider(LLMProvider):
    def __init__(self):
        self.api_key = os.environ.get("VALLEN_LLM_API_KEY")
        if not self.api_key:
            raise ValueError("VALLEN_LLM_API_KEY not set")

    def get_action(self, prompt: str) -> str:
        # Actual implementation would use openai python SDK
        # return client.chat.completions.create(...)
        return '{"action": "end_phase"}' # Mock for now

class MockProvider(LLMProvider):
    def __init__(self, forced_action: Optional[Dict] = None):
        self.forced_action = forced_action

    def get_action(self, prompt: str) -> str:
        if self.forced_action:
            return json.dumps(self.forced_action)
        return '{"action": "end_phase"}'

class LLMOpponent:
    def __init__(self, provider: LLMProvider):
        self.provider = provider

    def construct_prompt(self, state_serialized: Dict, legal_actions: List[Dict]) -> str:
        prompt = (
            "You are a strategic expert in the Vallen card game. "
            "Your goal is to reduce the opponent's LP to 0 while protecting your own units.\n\n"
            f"CURRENT GAME STATE:\n{json.dumps(state_serialized, indent=2)}\n\n"
            f"LEGAL ACTIONS:\n{json.dumps(legal_actions, indent=2)}\n\n"
            "You must respond ONLY with a single JSON object representing your chosen action "
            "from the LEGAL ACTIONS list. Do not provide any explanation."
        )
        return prompt

    def choose_action(self, state_serialized: Dict, legal_actions: List[Dict]) -> Dict[str, Any]:
        prompt = self.construct_prompt(state_serialized, legal_actions)
        response = self.provider.get_action(prompt)
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            raise ValueError(f"LLM returned malformed JSON: {response}")
