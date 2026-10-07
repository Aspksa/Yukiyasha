"""AI assistant module."""

from yukiyasha.modules.ai.errors import (
    AiBusyError,
    AiError,
    AiNotConfiguredError,
    ConversationNotFoundError,
    MessageRejectedError,
    ProviderError,
)
from yukiyasha.modules.ai.module import (
    AI_MANIFEST,
    CHATS_DIR,
    PERSONA_PATH,
    AiModule,
    ChatTurn,
)
from yukiyasha.modules.ai.provider import ChatProvider, OpenAICompatibleProvider

__all__ = [
    "AI_MANIFEST",
    "CHATS_DIR",
    "PERSONA_PATH",
    "AiBusyError",
    "AiError",
    "AiModule",
    "AiNotConfiguredError",
    "ChatProvider",
    "ChatTurn",
    "ConversationNotFoundError",
    "MessageRejectedError",
    "OpenAICompatibleProvider",
    "ProviderError",
]
