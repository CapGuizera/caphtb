# caphtb

CLI bonita (e industrial) para a API v4 do **Hack The Box**, construida com
`typer` + `rich`. Lista e controla maquinas, acompanha first bloods ao vivo,
explora challenges (DFIR, Pwn, Forensics...) e mostra rankings mundial, por
pais, por time e por universidade.

```
  ___ __ _ _ __ | |__ | |_| |__
 / __/ _` | '_ \| '_ \| __| '_ \
| (_| (_| | |_) | | | | |_| |_) |
 \___\__,_| .__/|_| |_|\__|_.__/
          |_|   hack the box cli
```

---

## Instalacao rapida

```bash
chmod +x start.sh
./start.sh            # cria .venv, instala tudo e mostra a ajuda
./start.sh login      # cola seu App Token (fica salvo so localmente)
```

O `start.sh` cria um virtualenv isolado em `.venv/`, instala as dependencias
e repassa qualquer argumento para o comando `caphtb`.

### Instalacao manual (opcional)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
caphtb --help
```

---

## Autenticacao

1. Gere um **App Token** em <https://app.hackthebox.com/profile/settings>
   (aba *App Tokens* / *Create App Token*).
2. Rode `caphtb login` e cole o token. Ele e gravado em
   `~/.config/caphtb/config.json` com permissao `0600`.

Alternativa sem gravar em disco: exporte `HTB_TOKEN`.

```bash
export HTB_TOKEN="eyJ0eXAiOiJKV1Qi..."
```

> O token e um segredo. Nunca o coloque em repositorio nem compartilhe.
> O `.gitignore` ja bloqueia `config.json`, `.env` e `*.token`.

---

## Modo de uso

Cada comando tem `--help` proprio (`caphtb machines --help`).

### Perfil

| Comando            | O que faz                                            |
|--------------------|------------------------------------------------------|
| `caphtb login`     | Salva e valida seu App Token                         |
| `caphtb whoami`    | Seu perfil: rank, pontos, owns e time                |
| `caphtb config`    | Mostra a config atual (sem revelar o token)          |
| `caphtb version`   | Versao da ferramenta                                 |

### Maquinas

```bash
caphtb machines                       # ativas
caphtb machines --retired             # aposentadas
caphtb machines --os linux -d easy    # filtra OS e dificuldade
caphtb machines --todo                # so as da sua lista de to-do
caphtb machines --search lame         # busca por nome
caphtb machine Lame                   # detalhe (id ou nome)
caphtb active                         # qual maquina voce tem spawnada
caphtb startingpoint 1                # starting point por tier
```

Filtros de `machines`: `--retired/-r`, `--os`, `--difficulty/-d`,
`--todo`, `--search/-s`, `--limit/-n`.

### Ciclo de vida da VM

```bash
caphtb spawn Lame          # inicia (aceita id ou nome)
caphtb active              # ver o IP depois de alguns segundos
caphtb stop                # desativa a maquina ativa
caphtb stop Lame           # desativa uma especifica
caphtb reset Lame          # reseta a instancia
caphtb submit Lame "HTB{...}" -d 4   # envia flag (dificuldade 1-10)
```

### Bloods e acompanhamento ao vivo

```bash
caphtb bloods Lame                 # first bloods + top owns
caphtb watch Lame                  # ATUALIZA SOZINHO e avisa o blood
caphtb watch Lame --interval 15    # intervalo de polling em segundos
```

O `watch` e feito para maquinas recem-lancadas: a tela se atualiza
sozinha, e quando o **user blood** ou o **root blood** e capturado a
ferramenta destaca em vermelho e toca o bell do terminal.

### Challenges (inclui DFIR)

```bash
caphtb challenges                          # ativos
caphtb challenges -c DFIR                  # por categoria
caphtb challenges -c Pwn -d hard --todo    # categoria + dificuldade + nao resolvidos
caphtb challenges --retired                # aposentados
caphtb dfir                                # atalho da categoria DFIR
caphtb dfir --todo                         # DFIR ainda nao resolvidos
caphtb categories                          # lista as categorias
caphtb challenge 123                       # detalhe de um challenge
caphtb challenge-submit 123 "HTB{...}" -d 3
```

### Ranking

```bash
caphtb ranking world                 # Hall of Fame mundial
caphtb ranking country --country BR  # por pais (default: BR)
caphtb ranking team                  # times
caphtb ranking uni                   # universidades
caphtb ranking world -n 50           # quantos linhas exibir
```

---

## Estrutura do projeto

```
caphtb_cli/
├── caphtb/
│   ├── __init__.py     # metadados do pacote
│   ├── __main__.py     # permite `python -m caphtb`
│   ├── config.py       # token + config + leitura do JWT
│   ├── api.py          # cliente HTTP da API v4 do HTB
│   ├── ui.py           # tema, banner, tabelas e paineis (rich)
│   └── cli.py          # comandos (typer)
├── requirements.txt
├── pyproject.toml      # empacotamento + entrypoint `caphtb`
├── start.sh            # instalador/lancador
├── .gitignore
├── LICENSE
└── README.md
```

---

## Notas tecnicas

- **Base da API:** `https://labs.hackthebox.com/api/v4`. Da para trocar
  editando `base_url` no `config.json` caso o HTB mude o dominio.
- **Id do usuario:** lido do claim `sub` do proprio JWT, sem chamada extra.
- **Endpoints de challenge:** o HTB ja renomeou esses endpoints; o cliente
  tenta o caminho novo (`/challenges`) e cai para o legado (`/challenge/list`).
- **Rate limit:** chamadas em excesso retornam `429`; o `watch` usa polling
  espacado (default 20s) justamente para nao bater no limite.

---

## Licenca

MIT. Veja `LICENSE`.
