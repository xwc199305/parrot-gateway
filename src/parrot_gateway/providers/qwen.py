from parrot_gateway.providers.openai import OpenAIAdaptor


class QwenAdaptor(OpenAIAdaptor):
    """Qwen/DashScope adaptor using its OpenAI-compatible endpoint."""

    name = "qwen"
