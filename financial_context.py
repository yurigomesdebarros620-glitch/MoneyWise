"""Consulta somente leitura dos registros atuais para o assistente local."""

# GUIA DE LEITURA: transforma os cadastros em um resumo para o assistente.
# Lê o banco -> identifica período e assunto -> calcula totais -> monta um dicionário.
# Não treina o modelo e não modifica receitas, despesas ou metas.
import math
import re
import unicodedata
from datetime import date, timedelta


# Remove acentos e padroniza letras para facilitar a busca por nomes.
def normalize(text):
    # Exemplo: "Alimentação" vira "alimentacao". Isso facilita comparar palavras
    # mesmo quando a pergunta foi escrita sem acento ou com letras maiúsculas.
    return "".join(
        c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn"
    )


# Monta um resumo atualizado dos registros para responder à pergunta.
def financial_context(connection, question, history=(), user_id=1):
    today = date.today()
    # Um único snapshot, renovado a cada pergunta. Nunca executar SQL vindo da IA.
    # Lê lançamentos e metas no mesmo retrato do banco, sem alterar os dados.
    # BEGIN inicia uma leitura consistente das duas tabelas.
    # rollback encerra essa transação de leitura; aqui não há alterações para desfazer.
    connection.execute("BEGIN")
    transactions = [
        dict(row)
        for row in connection.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY date DESC,id DESC", (user_id,))
    ]
    targets = [dict(row) for row in connection.execute("SELECT * FROM goals WHERE user_id=? ORDER BY id DESC", (user_id,))]
    connection.rollback()
    text = normalize(question)
    # Identifica o período mencionado, como mês atual, mês passado ou uma data.
    period = None
    # any devolve True se encontrar pelo menos um dos termos indicados na pergunta.
    # Por padrão, datas futuras não entram como dinheiro já recebido ou gasto.
    include_future = any(word in text for word in ("futur", "agendad", "previst"))
    period_name = "todo o histórico cadastrado (inclui datas futuras)" if include_future else "todo o histórico até hoje"
    if "mes passado" in text or "mes anterior" in text:
        # Volta ao primeiro dia do mês e subtrai um dia para encontrar o mês anterior.
        # A conta também funciona na passagem de janeiro para dezembro do ano anterior.
        period = (today.replace(day=1) - timedelta(days=1)).isoformat()[:7]
    elif any(term in text for term in ("este mes", "nesse mes", "neste mes", "mes atual")):
        period = today.isoformat()[:7]
    else:
        # Expressões regulares procuram padrões de texto; esta procura um mês como 2026-11.
        found = re.search(r"\b(\d{4})-(0[1-9]|1[0-2])\b", text)
        if found:
            period = found.group(0)
        months = [
            "janeiro",
            "fevereiro",
            "marco",
            "abril",
            "maio",
            "junho",
            "julho",
            "agosto",
            "setembro",
            "outubro",
            "novembro",
            "dezembro",
        ]
        for index, month in enumerate(months, 1):
            if re.search(r"\b" + month + r"\b", text):
                year = re.search(r"\b(20\d{2})\b", text)
                period = f"{year.group(1) if year else today.year}-{index:02}"
                break
    # Aplica os filtros de período e de tipo de movimentação.
    selected = transactions if include_future or (period and period > today.isoformat()[:7]) else [t for t in transactions if t["date"] <= today.isoformat()]
    if period:
        selected = [t for t in selected if t["date"].startswith(period)]
        period_name = period + (" (inclui agendamentos)" if include_future or period > today.isoformat()[:7] else " (até hoje)")
    elif "hoje" in text:
        selected = [t for t in selected if t["date"] == today.isoformat()]
        period_name = today.isoformat()
    kinds = []
    if any(w in text for w in ("despesa", "gastei", "gasto", "saida", "paguei")):
        kinds.append("despesa")
    if any(w in text for w in ("receita", "recebi", "entrada", "ganhei")):
        kinds.append("receita")
    if len(kinds) == 1:
        selected = [t for t in selected if t["type"] == kinds[0]]
    # Ignora palavras comuns para destacar nomes como mercado ou viagem.
    # Este conjunto contém palavras que não ajudam a identificar um lançamento.
    # Em "quanto gastei com mercado", a ideia é destacar "mercado" para a busca.
    stop = set(
        "a o as os de da do das dos em no na nos nas um uma e eu meu minha meus minhas quanto quantos qual quais como foi foram tenho tem total valor valores sobre para por que se voce pode poderia me dizer mostrar ver saber adicionei cadastrei despesa despesas receita receitas meta metas gasto gastos gastei paguei recebi ganhei entrada entradas saida saidas saldo falta guardar mes atual este esse neste nesse passado anterior hoje historico tudo todos todas ao longo uso".split()
    )
    stop.update(
        [
            "janeiro",
            "fevereiro",
            "marco",
            "abril",
            "maio",
            "junho",
            "julho",
            "agosto",
            "setembro",
            "outubro",
            "novembro",
            "dezembro",
        ]
    )
    stop.update("com preciso progresso financeiro financeiro minhas financas situacao foi hoje registrado cadastrados registrada registradas ate incluindo agendado agendados total totais isso dessa esse essa desta deste disso falta preciso esta estao onde maior categoria mais gastando dinheiro analisar analise economizar economizo reduzir gastos poupar melhor resumo quanto mes mensal nesse mes este tenho consulte dados dos resuma agora daqui".split())
    terms = [
        w
        for w in re.findall(r"[a-z0-9]+", text)
        if len(w) > 2 and w not in stop and not w.isdigit()
    ]

    # Conta as palavras da pergunta encontradas no nome ou na categoria.
    # Esta função interna é usada só durante a montagem do resumo.
    # Quanto mais palavras combinarem com descrição/categoria, maior será a pontuação.
    def score(row, fields):
        content = normalize(" ".join(str(row[f]) for f in fields))
        return sum(1 for word in terms if word in content)

    # Prioriza os registros com palavras relacionadas à pergunta.
    ranked = sorted(selected, key=lambda r: score(r, ("description", "category")), reverse=True)
    matched = [r for r in ranked if score(r, ("description", "category"))]
    # Só restringir por nome quando há correspondência real; declarar o critério.
    # Só filtra por nome quando encontra uma correspondência real.
    # Sem correspondência, mantém os registros do período e informa "sem filtro por nome".
    # Quem monta a resposta deve verificar esse critério para não atribuir gastos a outro nome.
    search_rows = matched if matched else selected
    criterion = "correspondência por descrição/categoria" if matched else "sem filtro por nome"
    goal_ranked = sorted(targets, key=lambda r: score(r, ("name",)), reverse=True)
    goal_matches = [r for r in goal_ranked if score(r, ("name",))]
    # O histórico ajuda apenas perguntas curtas como "e essa meta?".
    # Usa a pergunta anterior para referências curtas, como “essa meta”.
    if not matched and not goal_matches and len(terms) <= 1 and history:
        previous = next((h["content"] for h in reversed(history) if h["role"] == "user"), "")
        previous_terms = [
            w
            for w in re.findall(r"[a-z0-9]+", normalize(previous))
            if len(w) > 2 and w not in stop and not w.isdigit()
        ]
        if previous_terms:
            terms = previous_terms
            goal_ranked = sorted(targets, key=lambda r: score(r, ("name",)), reverse=True)
            goal_matches = [r for r in goal_ranked if score(r, ("name",))]

    # Soma todos os resultados em centavos e converte os totais para reais.
    # Os totais usam todos os resultados filtrados, não apenas os itens mostrados na lista.
    # Exemplo: 15 despesas de R$ 10 somam R$ 150, mesmo que só 12 sejam detalhadas.
    def totals(rows):
        income = sum(t["amount"] for t in rows if t["type"] == "receita")
        expense = sum(t["amount"] for t in rows if t["type"] == "despesa")
        return {
            "quantidade": len(rows),
            "receitas": income / 100,
            "despesas": expense / 100,
            "diferenca": (income - expense) / 100,
        }

    # Seleciona os campos do lançamento enviados ao modelo local.
    def transaction(row):
        return {
            "descricao": row["description"],
            "valor": row["amount"] / 100,
            "tipo": row["type"],
            "categoria": row["category"],
            "data": row["date"],
        }

    # Calcula o valor restante e a economia mensal necessária para a meta.
    def goal(row):
        # Subtrai o que já foi guardado do objetivo. max evita um restante negativo.
        # A sugestão mensal divide o restante pelo prazo aproximado em meses.
        remaining = max(0, row["target"] - row["saved"])
        months = max(1, math.ceil((date.fromisoformat(row["deadline"]) - today).days / 30.4375))
        return {
            "nome": row["name"],
            "objetivo": row["target"] / 100,
            "guardado": row["saved"] / 100,
            "falta": remaining / 100,
            "prazo": row["deadline"],
            "guardar_por_mes": round(remaining / 100 / months, 2),
        }

    # O saldo usa lançamentos até hoje; metas não movimentam a conta.
    actual = [t for t in transactions if t["date"] <= today.isoformat()]
    current = [t for t in actual if t["date"].startswith(today.isoformat()[:7])]
    # Um dicionário associa cada categoria ao total gasto nela no mês.
    # get(..., 0) começa em zero quando a categoria aparece pela primeira vez.
    category_totals = {}
    for item in current:
        if item["type"] == "despesa":
            category_totals[item["category"]] = category_totals.get(item["category"], 0) + item["amount"]
    # As listas finais têm limite de detalhes para poupar espaço no contexto do modelo.
    # Os campos de itens omitidos avisam que existem outros cadastros além dos exibidos.
    shown_goals = goal_matches if goal_matches else goal_ranked
    # Limita os detalhes enviados, mantendo os totais de todos os resultados.
    return {
        "atualizado_em": today.isoformat(),
        "moeda": "BRL",
        "saldo_acumulado": totals(actual)["diferenca"],
        "mes_atual": totals(current),
        "total_registros": len(transactions),
        "total_metas": len(targets),
        "metas_encontradas_por_nome": len(goal_matches),
        "despesas_por_categoria_no_mes": [
            {"categoria": category, "total": amount / 100}
            for category, amount in sorted(category_totals.items(), key=lambda item: -item[1])
        ],
        "consulta": {
            "periodo": period_name,
            "tipos": kinds or ["receita", "despesa"],
            "criterio": criterion,
            "termos": terms,
            "totais_exatos_dos_resultados": totals(search_rows),
            "lancamentos": [transaction(t) for t in search_rows[:12]],
            "detalhes_omitidos": max(0, len(search_rows) - 12),
        },
        "metas": [goal(g) for g in shown_goals[:8]],
        "metas_omitidas": max(0, len(shown_goals) - 8),
        "observacao": "Resumo atual tem prioridade sobre respostas antigas. Se a busca não localizar o nome pedido, não atribua outros registros a ele. Totais incluem todos os resultados; listas detalhadas são limitadas. Peça um nome ou mês para refinar. Metas não movimentam saldo.",
    }
