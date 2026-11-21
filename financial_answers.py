"""Respostas verificáveis: números vêm do SQLite, nunca de uma estimativa da IA."""

# GUIA DE LEITURA: responde algumas perguntas usando regras e totais do resumo.
# Isso dispensa a IA em consultas simples e evita pedir ao modelo que faça as contas.
# Quando a pergunta não cabe nessas regras, devolve None para o app chamar o Ollama.
import re
from financial_context import normalize


# Formata um número para exibição: 1234.5 vira "R$ 1.234,50".
# A marca temporária permite trocar ponto e vírgula sem confundir os separadores.
def reais(value):
    return "R$ " + f"{value:,.2f}".replace(",", "_perm_").replace(".", ",").replace("_perm_", ".")


def answer_from_data(question, context):
    """Atende intenções simples; perguntas abertas continuam para o modelo local."""
    # Se o usuário desativou o uso de seus dados, não há contexto para consultar.
    if context is None:
        return None
    text = normalize(question).strip(" ?.!\n")
    query = context["consulta"]
    total = query["totais_exatos_dos_resultados"]
    period = query["periodo"]
    # Não presumir uma consulta numérica em pedidos de explicação ou conselhos.
    if any(word in text for word in ("explique", "por que", "porque", "como ", "devo ", "sugira")):
        return None
    # fullmatch exige que a pergunta inteira combine com o padrão de consulta de saldo.
    # Uma frase mais ampla pode precisar do modelo, em vez de receber apenas o saldo.
    if re.fullmatch(r"(?:qual (?:e |o |e o )?|meu |o |mostrar |mostre |ver )*saldo(?: atual| total| acumulado| disponivel| da conta| meu)?", text):
        return f"Seu saldo acumulado até hoje é {reais(context['saldo_acumulado'])}. Ele considera receitas menos despesas já registradas até hoje; valores guardados em metas não são descontados."
    if re.search(r"\b(?:quanto falta|quanto (?:preciso )?guardar|progresso)\b", text) and "meta" in text:
        goals = context["metas"]
        if not context["total_metas"]:
            return "Você ainda não cadastrou metas. Abra Minhas metas para definir um objetivo e acompanhar quanto falta."
        # Só responde diretamente quando consegue identificar uma única meta sem ambiguidade.
        if len(goals) != 1 or (query["termos"] and not context.get("metas_encontradas_por_nome")):
            return None
        goal = goals[0]
        return f"Na meta {goal['nome']}, você guardou {reais(goal['guardado'])} de {reais(goal['objetivo'])}. Faltam {reais(goal['falta'])}; a referência é guardar {reais(goal['guardar_por_mes'])} por mês até {goal['prazo']}."
    # Só assumir um período quando o usuário o informou. Para valores sem mês,
    # o resumo considera o histórico até hoje, salvo pedido que inclua datas futuras.
    spending = bool(("quanto" in text and re.search(r"\b(?:gastei|paguei)\b", text)) or re.search(r"\btotal (?:de |das |dos )?(?:despesas|gastos)\b", text))
    income = bool(("quanto" in text and re.search(r"\b(?:recebi|ganhei)\b", text)) or re.search(r"\btotal (?:de |das )?receitas\b", text))
    # A diferença entre os dois booleanos significa que apenas uma intenção foi detectada: 
    # ou despesas ou receitas. Perguntas que misturam ambas seguem para o modelo.
    if spending != income:
        if query["termos"] and query["criterio"] == "sem filtro por nome":
            return "Não encontrei lançamentos com essa descrição ou categoria no período consultado. Confira o nome ou informe outro mês; não vou atribuir outros gastos a essa busca."
        value = total["despesas" if spending else "receitas"]
        verb = "despesas" if spending else "receitas"
        scope = "nos registros encontrados" if query["criterio"] != "sem filtro por nome" else "nos seus registros"
        return f"O total de {verb} é {reais(value)} {scope}. Período: {period}. Foram considerados todos os resultados da consulta, mesmo os que não aparecem na lista resumida."
    if re.fullmatch(r"(?:resumo|resumo financeiro|resumo do mes|como estao minhas financas|minha situacao financeira)", text):
        month = context["mes_atual"]
        return f"Seu saldo acumulado é {reais(context['saldo_acumulado'])}. Neste mês, até hoje, entraram {reais(month['receitas'])} e saíram {reais(month['despesas'])}, uma diferença de {reais(month['diferenca'])}. Você tem {context['total_metas']} meta(s) cadastrada(s)."
    return None
