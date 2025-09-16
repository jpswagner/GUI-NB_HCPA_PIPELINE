#!/usr/bin/env bash
set -Eeuo pipefail
trap 'echo "[ERROR] line $LINENO failed" >&2' ERR

# ==================== CONFIG ====================
ENV_NAME="NB_HCPA_Workflow"
CONDADIR="${CONDADIR:-$HOME/miniconda3}"   # pode sobrescrever via export CONDADIR=/caminho
APP_ENTRY="${APP_ENTRY:-app.py}"           # arquivo principal da sua GUI
APT_MIN_PKGS=(curl ca-certificates bzip2 xz-utils)
CONDA_CHANNELS=(-c conda-forge -c bioconda)

# ==================== HELP ======================
usage() {
  cat <<USAGE
Uso: $0 <install|verify|uninstall> [opções]

Comandos:
  install                 Instala/atualiza ambiente conda e ferramentas (fastp/fastqc, tk)
  verify                  Verifica instalação (conda, ambiente, pacotes, Tkinter, fastp/fastqc)
  uninstall [--purge-conda]
                          Remove o ambiente $ENV_NAME.
                          --purge-conda  (opcional) também remove o Miniconda em $CONDADIR
                                         (se foi instalado ali e você confirmar)

Variáveis ajustáveis (via export):
  CONDADIR=/caminho       Caminho do Miniconda (default: \$HOME/miniconda3)
  APP_ENTRY=app.py        Nome do arquivo que inicia a GUI (default: app.py)
USAGE
}

# ==================== UTILS =====================
need() { command -v "$1" >/dev/null 2>&1 || { echo "missing: $1" >&2; exit 1; }; }

is_debian_like() { command -v apt-get >/dev/null 2>&1; }
ensure_apt_mins() {
  ! is_debian_like && return 0
  local missing=()
  for p in "${APT_MIN_PKGS[@]}"; do
    dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
  done
  if ((${#missing[@]})); then
    local SUDO=""
    if [[ ${EUID:-$(id -u)} -ne 0 ]]; then need sudo; SUDO="sudo"; fi
    export DEBIAN_FRONTEND=noninteractive
    $SUDO apt-get update -y
    $SUDO apt-get install -y "${missing[@]}"
  fi
}

load_conda() {
  # shellcheck disable=SC1091
  source "$CONDADIR/etc/profile.d/conda.sh" 2>/dev/null || {
    echo "[INFO] conda.sh não encontrado em $CONDADIR; tentando 'conda init' não-invasivo..."
    [[ -x "$CONDADIR/bin/conda" ]] || return 1
    "$CONDADIR/bin/conda" shell.bash hook >/dev/null 2>&1 || return 1
  }
}

conda_tos_accept() {
  conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/main || true
  conda tos accept --override-channels --channel https://repo.anaconda.com/pkgs/r || true
}

ensure_miniconda() {
  if [[ ! -x "$CONDADIR/bin/conda" ]]; then
    echo "[INFO] instalando Miniconda em $CONDADIR..."
    local TMP="$HOME/Miniconda3-latest-Linux-x86_64.sh"
    curl -fsSL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o "$TMP"
    bash "$TMP" -b -p "$CONDADIR"
    rm -f "$TMP"
  fi
  load_conda || { echo "[ERRO] Não foi possível carregar o conda em $CONDADIR"; exit 1; }
  conda_tos_accept
}

env_exists() {
  conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"
}

# ==================== ACTIONS ===================
do_install() {
  ensure_apt_mins
  ensure_miniconda

  if env_exists; then
    echo "[OK] Ambiente $ENV_NAME já existe. Garantindo dependências..."
    conda run -n "$ENV_NAME" mamba install -y "${CONDA_CHANNELS[@]}" tk fastp python=3.11 || {
      echo "[ERRO] Falha ao garantir pacotes no env $ENV_NAME"; exit 1;
    }
  else
    echo "[INFO] Criando ambiente $ENV_NAME..."
    conda create -y -n "$ENV_NAME" "${CONDA_CHANNELS[@]}" mamba python=3.11 tk
    conda run -n "$ENV_NAME" mamba install -y "${CONDA_CHANNELS[@]}" fastp fastqc
  fi

  # Instala MultiQC após fastp/fastqc
  conda run -n "$ENV_NAME" mamba install -y -c bioconda -c conda-forge multiqc

  mkdir -p fastp_output

  cat <<MSG

###################### pronto! ######################
Ambiente:   $ENV_NAME
Ferramentas: fastp$(conda run -n "$ENV_NAME" bash -lc 'command -v fastqc >/dev/null && echo " + fastqc"')
Tkinter:    incluído (pacote tk)

Para rodar sua GUI:
  source "$CONDADIR/etc/profile.d/conda.sh"
  conda activate $ENV_NAME
  python "$APP_ENTRY"

Ou sem ativar:
  conda run -n $ENV_NAME python "$APP_ENTRY"
####################################################
MSG
}

do_verify() {
  echo "=== Verificação da instalação ==="

  if [[ -x "$CONDADIR/bin/conda" ]]; then
    echo "[OK] Miniconda encontrado em $CONDADIR"
  else
    echo "[FALHA] Miniconda NÃO encontrado em $CONDADIR"
    exit 2
  fi

  load_conda || { echo "[FALHA] Não foi possível carregar conda.sh"; exit 2; }

  if env_exists; then
    echo "[OK] Ambiente $ENV_NAME existe"
  else
    echo "[FALHA] Ambiente $ENV_NAME não existe"
    exit 2
  fi

  # Versões de Python e pacotes
  conda run -n "$ENV_NAME" python -V || { echo "[FALHA] Python não acessível no env"; exit 2; }
  conda run -n "$ENV_NAME" bash -lc 'python - <<PY
import tkinter as tk
print("Tkinter OK, TkVersion=", tk.TkVersion)
PY' || { echo "[FALHA] Tkinter indisponível (pacote tk ausente?)"; exit 2; }

  conda run -n "$ENV_NAME" bash -lc 'command -v fastp >/dev/null && echo "[OK] fastp encontrado" || echo "[FALHA] fastp ausente"'
  conda run -n "$ENV_NAME" bash -lc 'command -v fastqc >/dev/null && echo "[OK] fastqc encontrado" || echo "[AVISO] fastqc ausente (opcional)"'
  conda run -n "$ENV_NAME" bash -lc 'multiqc --version >/dev/null 2>&1 && echo "[OK] multiqc encontrado" || echo "[FALHA] multiqc ausente"'

  if [[ -f "$APP_ENTRY" ]]; then
    echo "[OK] App de entrada encontrado: $APP_ENTRY"
  else
    echo "[AVISO] Arquivo de entrada da GUI não encontrado: $APP_ENTRY (ajuste APP_ENTRY ou coloque o arquivo)"
  fi

  echo "=== Verificação concluída ==="
}

do_uninstall() {
  local purge_conda=0
  if [[ "${1:-}" == "--purge-conda" ]]; then purge_conda=1; fi

  if [[ -x "$CONDADIR/bin/conda" ]]; then
    load_conda || true
    if env_exists; then
      echo "Você deseja remover o ambiente '$ENV_NAME'? [y/N]"
      read -r ans
      if [[ "${ans,,}" == "y" ]]; then
        conda env remove -y -n "$ENV_NAME" || echo "[AVISO] Falha ao remover o ambiente (pode já não existir)"
        echo "[OK] Ambiente removido: $ENV_NAME"
      else
        echo "[INFO] Remoção do ambiente cancelada."
      fi
    else
      echo "[INFO] Ambiente $ENV_NAME não existe. Nada a remover."
    fi
  else
    echo "[AVISO] Miniconda não encontrado em $CONDADIR; pulando a remoção do ambiente."
  fi

  # Não apagamos dados do usuário (ex.: fastp_output)
  echo "[INFO] Pastas de saída do usuário foram preservadas (ex.: fastp_output)."

  if (( purge_conda )); then
    if [[ -x "$CONDADIR/bin/conda" ]]; then
      # Verifica se há outros ambientes além do 'base'
      local n_envs
      n_envs=$("$CONDADIR/bin/conda" env list | awk '/^\S/ {print $1}' | wc -l | tr -d ' ')
      echo "ATENÇÃO: isto irá remover TODO o Miniconda em: $CONDADIR"
      echo "Detectados $n_envs ambientes registrados (contando 'base')."
      echo "Prosseguir? [digite: REMOVE]"
      read -r confirm
      if [[ "$confirm" == "REMOVE" ]]; then
        rm -rf "$CONDADIR"
        echo "[OK] Miniconda removido de $CONDADIR"
      else
        echo "[INFO] Remoção do Miniconda cancelada."
      fi
    else
      echo "[AVISO] Miniconda não presente em $CONDADIR. Nada a purgar."
    fi
  fi

  echo "=== Desinstalação concluída ==="
}

# ==================== DISPATCH ==================
cmd="${1:-}"
case "$cmd" in
  install)   shift; do_install "$@";;
  verify)    shift; do_verify "$@";;
  uninstall) shift; do_uninstall "${1:-}";;
  -h|--help|"") usage;;
  *) echo "[ERRO] Comando desconhecido: $cmd"; usage; exit 1;;
esac
