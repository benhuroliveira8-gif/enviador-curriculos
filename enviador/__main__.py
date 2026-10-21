"""Uso:
    python -m enviador configurar  # assistente: responde perguntas e o config.yaml é criado
    python -m enviador painel      # abre o painel visual no navegador (recomendado)
    python -m enviador buscar      # procura vagas, analisa com seu currículo e mostra o ranking
    python -m enviador enviar      # idem, e se candidata por e-mail às recomendadas que têm endereço
    python -m enviador candidatar  # passa vaga a vaga no terminal: prepara respostas, abre o site
    python -m enviador diario      # rotina diária: busca e manda o resumo por e-mail
    python -m enviador feitas      # suas candidaturas e em que etapa estão
    python -m enviador etapa ID ETAPA ["observação"]   # ex.: etapa 12 entrevista "dia 20 às 14h"
    python -m enviador followup    # candidaturas sem resposta há muito tempo  (--feito ID para registrar)
    python -m enviador raiox       # o que as vagas pedem e falta no seu currículo
    python -m enviador curriculo   # sugestões para melhorar o currículo  (--ia para sugestões escritas pela IA)
    python -m enviador adicionar   # cadastra uma vaga de qualquer site (InfoJobs, LinkedIn...) colando a descrição
    python -m enviador reanalisar  # refaz com IA a análise das vagas avaliadas só por palavras
    python -m enviador entrevista ID   # prepara você para a entrevista daquela vaga  (--refazer)
    python -m enviador resultados  # o que avança e o que não avança nas suas candidaturas
    python -m enviador manuais     # lista as vagas recomendadas sem e-mail
    python -m enviador resumo      # estatísticas do histórico
    python -m enviador site        # roda o site público (envie um currículo, veja as vagas) em http://127.0.0.1:8000
"""
import argparse
import logging
import sys
from datetime import datetime

from .banco import ETAPAS, Banco
from .servico import ErroConfig, carregar_config, carregar_cv, enviar_por_email, rodar_busca, texto_analise

log = logging.getLogger("enviador")


def imprimir_ranking(analisadas):
    print(f"{'NOTA':>4}  {'':3} VAGA")
    for v, a in analisadas:
        marca = "✓" if a.recomendada else "·"
        destino = v.emails[0] if v.emails else "site"
        print(f"{a.nota:>4}  {marca:3} {v.titulo} | {v.empresa or '?'} | {destino}")
        if a.recomendada:
            print(f"           {texto_analise(a)}\n           {v.url}")
    print("\n✓ = recomendada (chance real)   · = descartada")


def cmd_buscar(config, banco, enviar: bool):
    res = rodar_busca(config, banco)
    print(f"\n{res.encontradas} vagas encontradas, {res.novas} novas.\n")
    if not res.novas:
        return
    imprimir_ranking(res.analisadas)
    rec = res.recomendadas
    print(f"\n{len(rec)} recomendadas: {sum(1 for v, _ in rec if v.aceita_email)} por e-mail, "
          f"{sum(1 for v, _ in rec if not v.aceita_email)} pelo site "
          f"(use o painel ou `python -m enviador candidatar`).\n")
    if enviar:
        enviar_por_email(config, banco, rec)


def _dias(iso):
    try:
        return (datetime.now() - datetime.fromisoformat(iso)).days
    except (TypeError, ValueError):
        return 0


def cmd_feitas(banco):
    linhas = banco.candidaturas()
    print(f"{len(linhas)} candidaturas:\n")
    print(f"{'ID':>4}  {'ETAPA':<20} {'HÁ':>6}  VAGA")
    for r in linhas:
        print(f"{r['id']:>4}  {ETAPAS.get(r['etapa'], r['etapa'] or '?'):<20} {_dias(r['etapa_em']):>4} d  "
              f"{r['titulo']} | {r['empresa'] or '?'}")
    print(f"\nPara atualizar: python -m enviador etapa ID ETAPA\nEtapas: {', '.join(ETAPAS)}")


def cmd_etapa(banco, args):
    if not args.id or not args.etapa:
        sys.exit(f"Uso: python -m enviador etapa ID ETAPA [\"observação\"]\nEtapas: {', '.join(ETAPAS)}")
    vaga = banco.vaga(args.id)
    if not vaga:
        sys.exit(f"Não encontrei a vaga {args.id}. Veja os IDs com `python -m enviador feitas`.")
    etapa = args.etapa.lower().replace("-", "_")
    if etapa not in ETAPAS:
        sys.exit(f"Etapa '{args.etapa}' não existe. Use uma de: {', '.join(ETAPAS)}")
    if vaga["status"] not in ("candidatei", "enviada"):
        banco.marcar(vaga["chave"], "candidatei")
    banco.registrar_etapa(vaga["chave"], etapa, args.obs or "")
    print(f"{vaga['titulo']} | {vaga['empresa'] or '?'} → {ETAPAS[etapa]}")


def cmd_followup(config, banco, feito):
    if feito:
        vaga = banco.vaga(feito)
        if not vaga:
            sys.exit(f"Não encontrei a vaga {feito}.")
        banco.marcar_followup(vaga["chave"])
        print(f"Follow-up registrado: {vaga['titulo']} | {vaga['empresa'] or '?'}. "
              f"O lembrete volta se ficar mais um período sem novidade.")
        return
    dias = config.get("acompanhamento", {}).get("dias_followup", 10)
    linhas = banco.followups(dias)
    if not linhas:
        print(f"Nenhuma candidatura parada há mais de {dias} dias. 👍")
        return
    print(f"{len(linhas)} candidatura(s) sem novidade há mais de {dias} dias:\n")
    for r in linhas:
        print(f"{r['id']:>4}  {r['titulo']} | {r['empresa'] or '?'} — {ETAPAS.get(r['etapa'], r['etapa'])} "
              f"há {_dias(r['etapa_em'])} dias\n      {r['url']}")
    print("\nSugestão de mensagem ao recrutador (LinkedIn ou e-mail):\n"
          "  \"Olá! Me candidatei à vaga de <cargo> há alguns dias e continuo muito interessado.\n"
          "   Gostaria de saber se há novidades sobre o processo. Obrigado pela atenção!\"\n"
          "\nDepois de enviar: python -m enviador followup --feito ID")


def cmd_curriculo(config, banco, com_ia):
    from . import curriculo, raiox
    cv = carregar_cv(config)
    vagas = banco.vagas_analisadas()
    rx = raiox.calcular(vagas, cv, config)
    area = [v for v in vagas if (v["nota"] or 0) >= (config.get("raiox") or {}).get("nota_minima_area", 30)]
    curriculo.imprimir(curriculo.sugestoes_regras(cv, rx, config, area))
    if com_ia:
        print("Pedindo sugestões à IA...\n")
        d = curriculo.sugestoes_ia(cv, rx, config)
        if d["resumo_sugerido"]:
            print("RESUMO SUGERIDO\n" + d["resumo_sugerido"] + "\n")
        for a in d["ajustes"]:
            print(f"- {a['secao']}: {a['sugestao']}" + (f"\n  Exemplo: {a['exemplo']}" if a["exemplo"] else ""))
        if d["palavras_chave"]:
            print("\nTermos para incluir: " + ", ".join(d["palavras_chave"]))


def _ler_varias_linhas(rotulo):
    print(f"{rotulo} Cole o texto e, numa linha sozinha, digite FIM e aperte Enter:")
    linhas = []
    while True:
        l = input()
        if l.strip().upper() == "FIM":
            return "\n".join(linhas)
        linhas.append(l)


def cmd_adicionar(config, banco, arquivo):
    from .servico import ErroVaga, adicionar_vaga
    titulo = input("Cargo: ").strip()
    empresa = input("Empresa: ").strip()
    url = input("Link da vaga: ").strip()
    cidade = input("Cidade (Enter se não souber): ").strip()
    remoto = input("É remota? [s/N]: ").strip().lower().startswith("s")
    if arquivo:
        descricao = open(arquivo, encoding="utf-8").read()
    else:
        descricao = _ler_varias_linhas("Descrição da vaga.")
    print("Analisando...")
    try:
        r, nova = adicionar_vaga(config, banco, titulo, descricao, empresa, url, cidade, remoto)
    except ErroVaga as e:
        sys.exit(str(e))
    if not nova:
        print(f"Essa vaga já estava cadastrada (ID {r['id']}, status {r['status']}).")
        return
    print(f"\nNota {r['nota']}: {r['titulo']} | {r['empresa'] or '?'}\n  {r['analise']}\n"
          f"Ela está na fila. Abra o painel ou rode `python -m enviador candidatar`.")


def cmd_entrevista(config, banco, id_, refazer):
    from . import entrevista
    if not id_:
        sys.exit("Uso: python -m enviador entrevista ID   (veja os IDs com `python -m enviador feitas`)")
    linha = banco.vaga(id_)
    if not linha:
        sys.exit(f"Não encontrei a vaga {id_}.")
    print("Preparando...")
    p = entrevista.preparo_do_banco(banco, linha, carregar_cv(config), config, refazer)
    texto = entrevista.texto(linha, p)
    print(texto)
    from pathlib import Path
    from .candidatura import nome_arquivo, vaga_do_banco
    pasta = Path("candidaturas"); pasta.mkdir(exist_ok=True)
    destino = pasta / ("Entrevista - " + nome_arquivo(vaga_do_banco(linha)))
    destino.write_text(texto, encoding="utf-8")
    print(f"Salvo em {destino}")


def main():
    ap = argparse.ArgumentParser(prog="enviador", description="Enviador automático de currículos")
    ap.add_argument("comando", choices=["configurar", "painel", "buscar", "enviar", "candidatar", "diario", "feitas",
                                        "etapa", "followup", "raiox", "curriculo", "adicionar", "reanalisar",
                                        "entrevista", "resultados", "manuais", "resumo", "site"])
    ap.add_argument("id", nargs="?", help="etapa: ID da vaga")
    ap.add_argument("etapa", nargs="?", help="etapa: nome da etapa")
    ap.add_argument("obs", nargs="?", help="etapa: observação opcional")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--banco", default="historico.db")
    ap.add_argument("--limite", type=int, help="candidatar: quantas vagas passar nesta sessão")
    ap.add_argument("--feito", help="followup: ID da vaga em que você já fez o follow-up")
    ap.add_argument("--porta", type=int, default=8765, help="painel: porta local")
    ap.add_argument("--ia", action="store_true", help="curriculo: pedir sugestões escritas pela IA")
    ap.add_argument("--refazer", action="store_true", help="entrevista: gerar o preparo de novo")
    ap.add_argument("--arquivo", help="adicionar: arquivo .txt com a descrição da vaga")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    if args.comando == "diario":
        from .diario import configurar_log
        configurar_log()
    elif sys.stderr:
        logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                            format="%(levelname)s %(message)s")
    logging.getLogger("pypdf").setLevel(logging.ERROR)

    if args.comando == "site":
        from .web import rodar as rodar_site
        return rodar_site(args.porta if args.porta != 8765 else 8000)

    if args.comando == "configurar":
        from .configuracao import assistente
        try:
            assistente(args.config)
        except (KeyboardInterrupt, EOFError):
            print("\nCancelado. Nada foi salvo.")
        return

    banco = Banco(args.banco)
    try:
        c = args.comando
        if c == "manuais":
            for r in banco.pendentes_manuais():
                print(f"[{r['nota']}] {r['titulo']} | {r['empresa'] or '?'}\n      {r['analise']}\n      {r['url']}\n")
            return
        if c == "feitas":
            return cmd_feitas(banco)
        if c == "etapa":
            return cmd_etapa(banco, args)
        if c == "resumo":
            for status, qtd in banco.resumo():
                print(f"{status}: {qtd}")
            print(f"enviados hoje: {banco.enviados_hoje()}")
            return

        config = carregar_config(args.config)
        if c == "followup":
            return cmd_followup(config, banco, args.feito)
        if c == "raiox":
            from . import raiox
            return raiox.imprimir(raiox.calcular(banco.vagas_analisadas(), carregar_cv(config), config))
        if c == "curriculo":
            return cmd_curriculo(config, banco, args.ia)
        if c == "resultados":
            from . import aprendizado
            return aprendizado.imprimir(aprendizado.analisar(banco, config))
        if c == "adicionar":
            return cmd_adicionar(config, banco, args.arquivo)
        if c == "reanalisar":
            from .servico import reanalisar
            print("Reanalisando com IA (pode levar alguns minutos)...")
            r = reanalisar(config, banco)
            print(f"{r['analisadas']} vagas analisadas com IA, {r['recomendadas']} recomendadas, "
                  f"{r['mudaram']} mudaram de lado (recomendada ↔ nota baixa).")
            return
        if c == "entrevista":
            return cmd_entrevista(config, banco, args.id, args.refazer)
        if c == "diario":
            from .diario import executar
            executar(config, banco, saida=lambda m: (print(m) if sys.stdout else None, log.info(m)))
            return
        if c == "painel":
            from .painel import rodar
            return rodar(config, args.banco, porta=args.porta, caminho_config=args.config)
        if c == "candidatar":
            from .candidatura import executar
            try:
                return executar(banco, carregar_cv(config), config, limite=args.limite)
            except (KeyboardInterrupt, EOFError):
                print("\nInterrompido. O que já foi marcado ficou salvo.")
                return
        cmd_buscar(config, banco, enviar=c == "enviar")
    except ErroConfig as e:
        sys.exit(str(e))
    except KeyboardInterrupt:
        print("\nInterrompido.")


if __name__ == "__main__":
    main()
