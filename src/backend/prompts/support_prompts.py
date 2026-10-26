"""Prompts LangChain structurés pour l'assistant support produit.

Ce module sépare la définition des prompts (`ChatPromptTemplate` avec `MessagesPlaceholder`)
de la logique d'exécution.
"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.backend.core.schemas import ChatMessage, ChatRequest


# Template du message système paramétré avec les métadonnées du ticket actif
SUPPORT_SYSTEM_TEMPLATE: str = (
    "Tu es l'assistant support produit de Nexus Platform.\n"
    "Tu assistes les agents du support technique et les responsables support B2B.\n\n"
    "=== CONTEXTE DU TICKET ACTIF ===\n"
    "- Identifiant Client : {client_id}\n"
    "- Sévérité déclarée : {severity}\n"
    "- Opérateur connecté : {operator_id} (Rôle : {operator_role})\n"
    "=== RÈGLES STRICTES DE GOUVERNANCE ===\n"
    "1. Validation humaine obligatoire : Toute réponse que tu proposes est un brouillon "
    "interne destiné à l'opérateur support. Elle doit toujours être validée par un humain "
    "avant envoi au client.\n"
    "2. Prudence sur les versions (v2 vs v3) : Si la résolution dépend de la version (v2.4.2 vs v3.x), "
    "distingue clairement les deux cas ou invite l'agent à vérifier la version du client.\n"
    "3. Interdiction de s'engager commercialement : Ne promets jamais "
    "d'avoir financier, de remise commerciale, ni de date de roadmap non vérifiée.\n"
    "4. Interdiction d'halluciner : Ne fournis jamais d'informations non vérifiées, "
    "si tu ne connais pas la réponse, dis le.\n"
    "5. Escalade : Si la sévérité est CRITICAL, s'il s'agit d'une faille de sécurité "
    "ou d'une réclamation contractuelle SLA, recommande immédiatement une escalade "
    "vers le Responsable Support (MANAGER).\n"
    "6. Langue et format : Réponds toujours en français, de manière structurée, "
    "concise et professionnelle."
)

# ChatPromptTemplate déclaratif incluant l'historique conversationnel et la question courante
support_chat_prompt = ChatPromptTemplate.from_messages(
    [
        ("system", SUPPORT_SYSTEM_TEMPLATE),
        MessagesPlaceholder(variable_name="history"),
        ("human", "{message}"),
    ]
)


def build_system_prompt(request: ChatRequest) -> str:
    """Construit le prompt système contextualisé.

    Injecte les métadonnées de base du ticket (`client_id`, `severity`, `operator_role`)
    et rappelle les consignes strictes de prudence et de validation humaine propres
    au copilote Nexus Platform.

    Args:
        request: Objet `ChatRequest` validé contenant le contexte du ticket.

    Returns:
        La chaîne de caractères complète du `SystemMessage` destinée au LLM.
    """
    return SUPPORT_SYSTEM_TEMPLATE.format(
        client_id=request.client_id,
        severity=request.severity.value,
        operator_id=request.operator_id,
        operator_role=request.operator_role.value,
    )


def convert_history_to_messages(history: list[ChatMessage]) -> list[BaseMessage]:
    """Convertit une liste de `ChatMessage` Pydantic en objets `BaseMessage` LangChain.

    Args:
        history: Liste des messages de l'historique conversationnel.

    Returns:
        Une liste ordonnée d'instances `HumanMessage`, `AIMessage` ou `SystemMessage`.
    """
    converted: list[BaseMessage] = []
    for hist_msg in history:
        if hist_msg.role == "user":
            converted.append(HumanMessage(content=hist_msg.content))
        elif hist_msg.role == "assistant":
            converted.append(AIMessage(content=hist_msg.content))
        elif hist_msg.role == "system":
            converted.append(SystemMessage(content=hist_msg.content))
    return converted


def build_langchain_messages(request: ChatRequest) -> list[BaseMessage]:
    """Assemble la séquence complète de messages LangChain via `support_chat_prompt`.

    Args:
        request: Objet `ChatRequest` contenant l'historique et le message courant.

    Returns:
        Une liste ordonnée d'instances `BaseMessage` prête à être envoyée au modèle.
    """
    history_messages = convert_history_to_messages(request.history)
    prompt_value = support_chat_prompt.invoke(
        {
            "client_id": request.client_id,
            "severity": request.severity.value,
            "operator_id": request.operator_id,
            "operator_role": request.operator_role.value,
            "history": history_messages,
            "message": request.message,
        }
    )
    return prompt_value.to_messages()
