"""Agent tools backed by the association knowledge Markdown file."""

from __future__ import annotations

from .knowledge import get_knowledge_store


def listar_modalidades() -> str:
    """Lista todas as modalidades/atividades oferecidas pela associação.

    Returns:
        Nome, horários e preços de cada modalidade cadastrada.
    """
    return get_knowledge_store().listar_modalidades()


def buscar_horarios_turmas(modalidade: str) -> str:
    """Consulta horários de uma modalidade específica.

    Args:
        modalidade: Nome da atividade (ex.: yoga, futebol adulto, dança).

    Returns:
        Horários e observações da modalidade solicitada.
    """
    return get_knowledge_store().buscar_horarios(modalidade)


def buscar_precos(modalidade: str = "") -> str:
    """Consulta preços mensais e regras de matrícula/pagamento.

    Args:
        modalidade: Nome da modalidade. Se vazio, retorna a tabela completa.

    Returns:
        Preço da modalidade ou tabela geral com taxa de matrícula e formas de pagamento.
    """
    return get_knowledge_store().buscar_precos(modalidade or None)


def buscar_info_associacao(topico: str) -> str:
    """Busca informações gerais sobre a associação.

    Args:
        topico: Assunto desejado (ex.: endereço, contato, matrícula, sobre a associação).

    Returns:
        Texto informativo sobre o tópico solicitado.
    """
    return get_knowledge_store().buscar_info(topico)


def buscar_faq(pergunta: str) -> str:
    """Consulta perguntas frequentes (FAQ) da associação.

    Args:
        pergunta: Dúvida do associado ou lead em linguagem natural.

    Returns:
        Resposta da FAQ mais relevante ou lista de perguntas disponíveis.
    """
    return get_knowledge_store().buscar_faq(pergunta)


def encaminhar_para_secretaria(motivo: str) -> str:
    """Encaminha o cliente para atendimento humano da secretaria.

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
