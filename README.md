# Enviador automático de currículos

Procura vagas todo dia, compara cada uma com o seu currículo, mostra onde você tem chance real
e ajuda a se candidatar e a acompanhar cada processo até a resposta.

## O que ele faz

- **Busca** vagas pelas suas palavras-chave na Gupy, na Adzuna (opcional) e em repositórios de vagas
  de tecnologia no GitHub. Filtra por cidade, remoto, data e termos que você não quer.
- **Analisa** cada vaga contra o seu currículo em PDF e dá uma nota de 0 a 100. Com a chave da
  Anthropic, a IA lê os requisitos como um recrutador e explica a nota (pontos a favor e lacunas).
- **Candidatura:** por e-mail, automaticamente, quando a vaga traz um endereço; pelo site, de forma
  semiautomática: o programa prepara as respostas e abre a vaga, você revisa e envia.
- **Acompanha** cada candidatura por etapas e avisa quando é hora de fazer follow-up.
- **Raio-x do mercado:** mostra o que as vagas da sua área mais pedem e você ainda não mostra no currículo.
- **Rotina diária:** roda sozinho de manhã e manda um e-mail só quando há vaga com nota alta,
  follow-up pendente ou algum erro.

## Instalação (Windows)

Precisa de Python 3.10 ou mais novo, de 64 bits.

```powershell
cd enviador-curriculos
py -3.13 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Se o `activate` reclamar de scripts desabilitados: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Configuração

1. Copie `config.example.yaml` para `config.yaml` e preencha seus dados e palavras-chave.
2. Coloque seu currículo como `curriculo.pdf` na pasta.
3. **E-mail (para candidaturas e para o aviso diário):** recomendo uma conta Gmail com *senha de app*
   (Conta Google → Segurança → Verificação em duas etapas → Senhas de app).
   Contas Hotmail/Outlook pessoais podem recusar login por SMTP.
4. **Análise com IA (recomendado):** crie uma chave em console.anthropic.com e rode
   `setx ANTHROPIC_API_KEY "sua-chave"`. Feche e abra o terminal depois.
5. **Adzuna (opcional):** cadastre-se grátis em developer.adzuna.com, coloque `app_id` e `app_key`
   em `busca.adzuna` e mude `busca.fontes.adzuna` para `true`. A Adzuna devolve só um trecho da
   descrição, então a análise dessas vagas é um pouco menos precisa.

## Uso no dia a dia

### Painel (recomendado)

```powershell
python -m enviador painel
```

Abre no navegador, só no seu computador. Deixe a janela do terminal aberta enquanto usa.

- **Para decidir:** vagas recomendadas, da maior nota para a menor. "Ver análise e respostas" mostra
  o que conta a seu favor, o que falta, e prepara os textos do formulário com botão de copiar.
  "Candidatei", "Depois" e "Descartar" têm desfazer.
- **Candidaturas:** quadro por etapa (enviada, em análise, teste, entrevista, proposta, encerradas).
  Mude a etapa na caixa de seleção; em entrevista, teste e proposta dá para anotar data e horário.
- **Follow-up:** candidaturas sem novidade há 10 dias ou mais, com mensagem pronta para o recrutador.
- **Raio-x do mercado:** o que mais aparece nas vagas da sua área, separado entre o que falta e o que você já tem.
- **Buscar vagas agora:** roda uma busca sem sair do painel.

### Rotina diária automática

```powershell
.\agendar_tarefa.ps1                 # todo dia às 08:47
.\agendar_tarefa.ps1 -Hora "07:52"   # outro horário
.\agendar_tarefa.ps1 -Remover        # desliga
```

A tarefa roda sem abrir janela. Se o computador estiver desligado no horário, ela roda quando ele
for ligado. Cada dia gera um resumo em `relatorios\` e um registro em `logs\diario.log`.
O e-mail só sai quando há novidade (vaga com nota a partir de `aviso.nota_alerta`, follow-up ou erro).
Para testar na hora: `python -m enviador diario`.

### Terminal

```powershell
python -m enviador buscar        # procura e analisa vagas, mostra o ranking
python -m enviador enviar        # se candidata por e-mail às recomendadas (respeita modo_teste)
python -m enviador candidatar    # candidatura semiautomática vaga a vaga  (--limite 5)
python -m enviador feitas        # suas candidaturas, com ID e etapa
python -m enviador etapa 12 entrevista "terça às 14h"
python -m enviador followup      # quem está sem resposta  (--feito 12 depois de cobrar)
python -m enviador raiox         # raio-x do mercado
python -m enviador diario        # roda a rotina diária agora
python -m enviador resumo        # estatísticas
```

Etapas: `candidatei`, `em_analise`, `teste`, `entrevista`, `proposta`, `aprovado`, `reprovado`,
`sem_resposta`, `desisti`.

## Proteções

- Candidatura por e-mail começa em **modo teste** (só mostra o que enviaria), com limite diário,
  espera aleatória entre envios, lista de empresas bloqueadas e cópia de cada envio para você.
- Nunca envia duas vezes para o mesmo e-mail.
- A IA usa só fatos do seu currículo e nunca inventa experiência.
- Não automatiza candidaturas em LinkedIn, Gupy ou Indeed: os termos de uso proíbem e a conta pode ser bloqueada.
- `config.yaml`, currículo, histórico e relatórios ficam só no seu computador.

## Testes

```powershell
pip install pytest
python -m pytest
```

## Próximo passo: versão para outras pessoas

O painel já roda como um app web local. Para abrir a outras pessoas, faltam: login e uma conta por
pessoa, banco de dados central (Postgres) separado por usuário, envio de e-mail pela conta de cada
um via login do Google/Microsoft (OAuth) em vez de senha, hospedagem, e termos de uso e política de
privacidade (LGPD), já que serão guardados currículos de terceiros. Vale fazer depois de algumas
semanas de uso, quando já estiver claro o que funciona.
