"""Agent tools backed by the association knowledge Markdown file."""

from __future__ import annotations

from .knowledge import get_knowledge_store


def listar_modalidades() -> str:
    """Lista todos os produtos, serviços ou modalidades cadastrados no negócio.

    Returns:
        Nome, horários/prazos e preços de cada item cadastrado.
    """
    return get_knowledge_store().listar_modalidades()


def buscar_horarios_turmas(modalidade: str) -> str:
    """Consulta horários de um produto, serviço ou modalidade específica.

    Args:
        modalidade: Nome do item cadastrado na base de conhecimento.

    Returns:
        Horários e observações do item solicitado.
    """
    return get_knowledge_store().buscar_horarios(modalidade)


def buscar_precos(modalidade: str = "") -> str:
    """Consulta preços e regras de compra/pagamento.

    Args:
        modalidade: Nome do item. Se vazio, retorna a tabela completa.

    Returns:
        Preço do item ou tabela geral com condições e formas de pagamento.
    """
    return get_knowledge_store().buscar_precos(modalidade or None)


def buscar_info_associacao(topico: str) -> str:
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
    listar_modalidades,
    buscar_horarios_turmas,
    buscar_precos,
    buscar_info_associacao,
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
