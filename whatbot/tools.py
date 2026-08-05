"""Agent tools backed by the business knowledge Markdown file."""

from __future__ import annotations

from .knowledge import get_knowledge_store


def listar_itens() -> str:
    """Lista todos os produtos, serviços ou itens cadastrados no negócio.

    Returns:
        Nome, horários/prazos e preços de cada item cadastrado.
    """
    return get_knowledge_store().listar_itens()


def buscar_horarios_turmas(item: str) -> str:
    """Consulta horários de um produto, serviço ou item específico.

    Args:
        item: Nome do item cadastrado na base de conhecimento.

    Returns:
        Horários e observações do item solicitado.
    """
    return get_knowledge_store().buscar_horarios(item)


def buscar_precos(item: str = "") -> str:
    """Consulta preços e regras de compra/pagamento.

    Args:
        item: Nome do item. Se vazio, retorna a tabela completa.

    Returns:
        Preço do item ou tabela geral com condições e formas de pagamento.
    """
    return get_knowledge_store().buscar_precos(item or None)


def buscar_info_negocio(topico: str) -> str:
    """Busca informações gerais sobre o negócio.

    Args:
        topico: Assunto desejado (ex.: endereço, contato, como comprar, sobre o negócio).

    Returns:
        Texto informativo sobre o tópico solicitado.
    """
    return get_knowledge_store().buscar_info(topico)


def buscar_faq(pergunta: str) -> str:
    """Consulta perguntas frequentes (FAQ) do negócio.

    Args:
        pergunta: Dúvida do cliente em linguagem natural.

    Returns:
        Resposta da FAQ mais relevante ou lista de perguntas disponíveis.
    """
    return get_knowledge_store().buscar_faq(pergunta)


def encaminhar_para_secretaria(motivo: str) -> str:
    """Encaminha o cliente para atendimento humano.

    Use SOMENTE quando o cliente pedir humano ou a informação essencial
    não existir nas outras ferramentas.

    Args:
        motivo: Breve explicação do motivo do encaminhamento.

    Returns:
        Confirmação com token interno de handover para o sistema.
    """
    motivo = (motivo or "Informação não disponível na base").strip()
    return f"[HUMAN_HANDOVER] {motivo}"


AGENT_TOOLS = [
    listar_itens,
    buscar_horarios_turmas,
    buscar_precos,
    buscar_info_negocio,
    buscar_faq,
    encaminhar_para_secretaria,
]

_TOOL_BY_NAME = {fn.__name__: fn for fn in AGENT_TOOLS}


def execute_tool(name: str, args: dict) -> str:
    """Run a tool by name (used in manual function-calling loop)."""
    fn = _TOOL_BY_NAME.get(name)
    if fn is None:
        return f"Ferramenta desconhecida: {name}"
    try:
        return str(fn(**args))
    except TypeError as exc:
        return f"Argumentos inválidos para {name}: {exc}"
