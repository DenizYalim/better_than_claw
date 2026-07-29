from .agent import Agent
from openai import OpenAI
import dotenv
import os

dotenv.load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class Openai(Agent):
    def get_response(self, prompt: str, context: str, model: str, conversation_id: str) -> str:  # conversation_id: str
        if not conversation_id:
            raise ValueError("conversation_id is required for get_response.")

        if not model:
            raise ValueError("model is required for get_response.")

        if not prompt:
            raise ValueError("prompt is required for get_response.")

        if not context:
            raise ValueError("context is required for get_response.")

        return client.responses.create(
            model=model,
            # reasoning={"effort": "low"},
            conversation=conversation_id,
            instructions=context,
            input=prompt,
        )


def __get_conversation_id() -> str:
    # Create a new conversation and return its ID
    convo = client.conversations.create()
    return convo.id


if __name__ == "__main__":
    print(__get_conversation_id())
