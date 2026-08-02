from .agent import Agent
from dataclasses import dataclass, field
from openai import OpenAI
from typing import Any
import dotenv
import json
import logging
import os

dotenv.load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """A finished turn: the reply plus what it cost.

    Tokens are summed over every request in the turn, not just the last one.
    A tool-using turn makes several calls and each one re-sends the whole
    conversation, so reporting only the final response would understate a
    four-round check-in several times over.
    """

    response: Any
    total_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    rounds: int = 1
    tool_calls: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return (self.response.output_text or "").strip()

    def add_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)

        if usage is None:
            return

        self.total_tokens += getattr(usage, "total_tokens", 0) or 0
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0

# A check-in legitimately chains several calls: list_tasks -> list_goals ->
# update_goal -> log_checkin. This caps a model that gets stuck calling the
# same tool forever, which would otherwise burn the API budget silently.
MAX_TOOL_ROUNDS = 8


class Openai(Agent):
    def get_response(self, prompt: str, context: str, model: str, conversation_id: str, tools=None) -> str:
        if not conversation_id:
            raise ValueError("conversation_id is required for get_response.")

        if not model:
            raise ValueError("model is required for get_response.")

        if not prompt:
            raise ValueError("prompt is required for get_response.")

        if not context:
            raise ValueError("context is required for get_response.")

        request = {
            "model": model,
            # reasoning={"effort": "low"},
            "conversation": conversation_id,
            "instructions": context,
            # A conversation grows with every message and is never trimmed.
            # The API default is truncation="disabled", which fails the request
            # with a 400 once the history outgrows the context window - and it
            # would keep failing forever after, since each new message replays
            # the same oversized history. "auto" drops the oldest turns instead.
            "truncation": "auto",
        }

        if tools is not None and len(tools):
            request["tools"] = tools.schemas()

        response = client.responses.create(input=prompt, **request)

        result = AgentResult(response=response)
        result.add_usage(response)

        if tools is None or not len(tools):
            return result

        for round_number in range(MAX_TOOL_ROUNDS):
            calls = _pending_calls(response)

            if not calls:
                return result

            # Only the outputs go back. The calls themselves are already stored
            # server-side against the conversation, so resending them would
            # duplicate the turn.
            outputs = [
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": tools.call(call.name, call.arguments),
                }
                for call in calls
            ]

            logger.info(
                "tool round %d: %s",
                round_number + 1,
                ", ".join(call.name for call in calls),
            )

            result.tool_calls.extend(call.name for call in calls)
            result.rounds += 1

            response = client.responses.create(input=outputs, **request)
            result.response = response
            result.add_usage(response)

        logger.warning("Hit MAX_TOOL_ROUNDS (%d); closing out.", MAX_TOOL_ROUNDS)

        return self._close_out(result, request)

    def _close_out(self, result, request):
        """Answer any tool calls left dangling, then force a text reply.

        Leaving a function_call unanswered corrupts the stored conversation
        permanently: every later message fails with "No tool output found for
        function call", so the chat is dead until someone resets it. The
        outputs below are refusals rather than results, and tool_choice="none"
        guarantees the model answers in text instead of opening another call
        we would again have to close.
        """

        calls = _pending_calls(result.response)

        if not calls:
            return result

        refusal = json.dumps(
            {"ok": False, "error": "Tool budget for this turn is used up. Answer with what you have."}
        )

        outputs = [
            {"type": "function_call_output", "call_id": call.call_id, "output": refusal}
            for call in calls
        ]

        try:
            response = client.responses.create(
                input=outputs, **{**request, "tool_choice": "none"}
            )
            result.response = response
            result.rounds += 1
            result.add_usage(response)
        except Exception:
            logger.exception("Could not close out dangling tool calls")

        return result


def _pending_calls(response) -> list:
    return [item for item in response.output if item.type == "function_call"]


def get_conversation_id() -> str:
    # Create a new conversation and return its ID
    convo = client.conversations.create()
    return convo.id


if __name__ == "__main__":
    print(get_conversation_id())
