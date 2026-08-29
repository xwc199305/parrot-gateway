from parrot_gateway.providers.openai import OpenAIAdaptor


class DeepseekAdaptor(OpenAIAdaptor):
    """DeepSeek's implementation of the OpenAI Chat Completions protocol."""

    name = "deepseek"
