#!/usr/bin/env bash
#
# start.sh - instalador/lancador da caphtb
# ----------------------------------------
# 1. Cria um virtualenv isolado em ./.venv (nao polui o sistema).
# 2. Instala a ferramenta e suas dependencias (typer, rich, requests).
# 3. Repassa os argumentos para o comando `caphtb`.
#
# Uso:
#   ./start.sh                 -> instala e mostra a ajuda
#   ./start.sh login           -> configura seu token
#   ./start.sh machines        -> lista maquinas ativas
#   ./start.sh ranking country --country BR
#
set -euo pipefail

# Diretorio onde este script esta, para funcionar de qualquer lugar.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

VENV_DIR="$SCRIPT_DIR/.venv"

# Cria o virtualenv apenas na primeira execucao.
if [ ! -d "$VENV_DIR" ]; then
    echo "[*] Criando ambiente virtual em .venv ..."
    python3 -m venv "$VENV_DIR"
fi

# Ativa o virtualenv.
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# Instala/atualiza a ferramenta de forma silenciosa (modo editavel).
if ! python -c "import caphtb" >/dev/null 2>&1; then
    echo "[*] Instalando dependencias e a caphtb ..."
    pip install --quiet --upgrade pip
    pip install --quiet -e .
fi

# Sem argumentos: mostra a ajuda. Com argumentos: repassa para o caphtb.
if [ "$#" -eq 0 ]; then
    caphtb --help
else
    caphtb "$@"
fi
