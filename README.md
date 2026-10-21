# Enviador de currículos

![Testes](https://github.com/benhuroliveira8-gif/enviador-curriculos/actions/workflows/testes.yml/badge.svg)

Procura vagas todo dia, compara cada uma com o seu currículo, mostra onde você tem chance real
e ajuda em tudo o que vem depois: candidatura, acompanhamento, follow-up e preparação para a entrevista.

## O que ele faz

- **Busca** vagas pelos cargos que você procura na Gupy (todas as áreas), na Adzuna (opcional) e em
  repositórios de vagas de programação no GitHub. Vagas do InfoJobs, LinkedIn, Catho ou de indicação
  entram pelo botão **Adicionar vaga**, colando a descrição.
- **Analisa** cada vaga contra o seu currículo em PDF e dá uma nota de 0 a 100. Com a chave da
  Anthropic, a IA lê os requisitos como um recrutador e explica a nota (o que conta a favor e o que falta).
- **Ajuda a se candidatar:** por e-mail, automaticamente, quando a vaga traz um endereço; pelos sites,
  preparando as respostas do formulário para você revisar e colar.
- **Acompanha** cada candidatura por etapa e lembra de fazer follow-up quando a empresa some.
- **Prepara para a entrevista:** perguntas prováveis para aquela vaga, como responder com fatos do seu
  currículo, perguntas para você fazer e o que pesquisar antes.
- **Raio-x e currículo:** o que as vagas da sua área mais pedem, o que falta no seu currículo e o que mudar nele.
- **Aprende com os resultados:** mostra que tipo de candidatura avança (por nota, fonte e cargo) e sugere ajustes.
- **Rotina diária:** roda sozinho de manhã e manda um e-mail só quando há vaga com nota alta, follow-up
  pendente ou algum erro.

Tudo roda no seu computador: currículo, senhas e histórico ficam na pasta do projeto. Com a análise
por IA ligada, o texto do currículo e das vagas é enviado à Anthropic para ser analisado.

## Instalação (Windows)

1. Baixe o projeto (botão verde **Code → Download ZIP** no GitHub) e extraia numa pasta.
2. Dê dois cliques em **`instalar.bat`**. Ele encontra ou instala o Python, instala o que precisa e
   abre um assistente que faz perguntas e monta a configuração.
3. Para usar no dia a dia, dê dois cliques em **`abrir_painel.bat`**.

Na primeira vez, o Windows pode mostrar "O Windows protegeu o computador". Clique em **Mais informações →
Executar assim mesmo**: o aviso aparece para qualquer arquivo baixado da internet.

<details>
<summary>Instalação manual (Windows, Mac ou Linux)</summary>

Precisa de Python 3.10 ou mais novo, de 64 bits.

```bash
python -m venv .venv
.venv\Scripts\activate          # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m enviador configurar
python -m enviador painel
```

No Mac/Linux, a rotina diária pode ser agendada com o `cron`, por exemplo:
`47 8 * * * cd /caminho/do/projeto && .venv/bin/python -m enviador diario`
</details>

## Configuração

Tudo pode ser feito pela aba **Configurações** do painel ou pelo assistente (`python -m enviador configurar`):

- **Seus dados e o resumo profissional**, que vão nas mensagens às empresas.
- **Cargos, cidades e termos para ignorar.**
- **Chave da Anthropic (recomendado):** crie em console.anthropic.com. Custa centavos por busca e é o que
  mais melhora o resultado: notas certeiras, respostas e preparação para entrevista sob medida.
  Depois de configurar, o painel oferece **Reanalisar com IA** as vagas avaliadas antes só por palavras.
- **E-mail que envia** as candidaturas e o resumo diário. No Gmail, use uma *senha de app*
  (Conta Google → Segurança → Verificação em duas etapas → Senhas de app). Contas Hotmail/Outlook
  pessoais costumam recusar esse tipo de acesso. Há um botão para testar o login.
- **Adzuna (opcional):** cadastro grátis em developer.adzuna.com.

Os dados ficam em `config.yaml`, que nunca vai para o GitHub (está no `.gitignore`).
A cada gravação, a versão anterior fica em `config.yaml.bak`.

## Uso no dia a dia

**Painel** (`abrir_painel.bat`):

| Aba | Para quê |
|---|---|
| Para decidir | Vagas recomendadas, da maior nota para a menor. Análise, respostas do formulário, e os botões Candidatei, Depois e Descartar (com desfazer). |
| Candidaturas | Quadro por etapa. Mude a etapa na caixa de seleção; **Preparar entrevista** em cada cartão. |
| Follow-up | Quem está sem resposta há dias, com mensagem pronta para o recrutador. |
| Raio-x e currículo | O que as vagas pedem, o que falta e sugestões para o currículo (com IA: novo resumo e trechos reescritos). |
| Resultados | Taxa de avanço por nota, fonte, cargo e modalidade, com sugestões de ajuste. |
| Configurações | Tudo o que está no `config.yaml`, com teste da chave da IA e do e-mail. |

**Rotina diária automática** (Windows):

```powershell
.\agendar_tarefa.ps1                 # todo dia às 08:47
.\agendar_tarefa.ps1 -Hora "07:52"   # outro horário
.\agendar_tarefa.ps1 -Remover        # desliga
```

Cada dia gera um resumo em `relatorios\` e um registro em `logs\diario.log`.

**Terminal** (com o `.venv` ativado):

```powershell
python -m enviador configurar       # assistente de configuração
python -m enviador buscar           # procura e analisa vagas
python -m enviador adicionar        # cadastra uma vaga de qualquer site, colando a descrição
python -m enviador reanalisar       # refaz com IA as análises feitas só por palavras
python -m enviador candidatar       # candidatura semiautomática, vaga a vaga  (--limite 5)
python -m enviador enviar           # candidatura por e-mail às recomendadas (respeita modo_teste)
python -m enviador feitas           # suas candidaturas, com ID e etapa
python -m enviador etapa 12 entrevista "terça às 14h"
python -m enviador entrevista 12    # prepara você para a entrevista da vaga 12  (--refazer)
python -m enviador followup         # quem está sem resposta  (--feito 12 depois de cobrar)
python -m enviador raiox            # o que as vagas pedem e falta no currículo
python -m enviador curriculo        # sugestões para o currículo  (--ia para sugestões da IA)
python -m enviador resultados       # o que avança e o que não avança
python -m enviador diario           # roda a rotina diária agora
```

## Proteções

- A candidatura por e-mail começa em **modo teste** (só mostra o que enviaria), com limite diário,
  espera aleatória entre envios, lista de empresas bloqueadas e cópia de cada envio para você.
- Nunca envia duas vezes para o mesmo e-mail.
- A IA usa só fatos do seu currículo e não inventa experiência. Onde faltar um dado, ela deixa
  [colchetes] para você completar.
- Não automatiza candidaturas nem coleta dados em LinkedIn, Gupy, InfoJobs ou Indeed por robô:
  os termos de uso desses sites proíbem e a conta pode ser bloqueada. A Gupy é consultada pela
  busca pública de vagas; os outros sites entram pelo botão Adicionar vaga.

## Para quem desenvolve

```bash
pip install pytest
python -m pytest
```

Os testes rodam sozinhos no GitHub a cada `git push` (Windows e Linux, Python 3.11 e 3.13).
O código fica em `enviador/`: `fontes.py` (busca), `analise.py` (nota), `painel.py` + `painel.html`
(interface), `entrevista.py`, `curriculo.py`, `raiox.py`, `aprendizado.py`, `diario.py` e `configuracao.py`.

Licença MIT (veja `LICENSE`).
