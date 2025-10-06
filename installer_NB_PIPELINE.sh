#!/usr/bin/env bash
set -Eeuo pipefail
trap 'echo "[ERROR] line $LINENO failed" >&2' ERR

# ==================== CONFIG ====================
ENV_NAME="NB_HCPA_Workflow"
CONDADIR="${CONDADIR:-$HOME/miniconda3}"   # sobrescrever via: export CONDADIR=/caminho
APP_ENTRY="${APP_ENTRY:-app.py}"           # arquivo principal da GUI

APT_MIN_PKGS=(curl ca-certificates bzip2 xz-utils)
CONDA_CHANNELS=(-c conda-forge -c bioconda)

# Inclui setuptools/pip/wheel para evitar hooks que dependem de pkg_resources (ex.: checkm)
CORE_PKGS=(python=3.11 tk mamba setuptools pip wheel fastp fastqc multiqc)
ASSEMBLY_PKGS=(spades unicycler quast)

RUN_SPADES_TEST="${RUN_SPADES_TEST:-0}"

# ==================== HELP ======================
usage() {
  cat <<USAGE
Uso: $0 <install|verify|uninstall>

Comandos:
  install                 Cria/atualiza o ambiente $ENV_NAME e instala: Python/Tk,
                          fastp/fastqc, MultiQC, SPAdes, Unicycler, QUAST
  verify                  Verifica (conda, env, versões). RUN_SPADES_TEST=1 roda spades.py --test
  uninstall [--purge-conda]
                          Remove o env $ENV_NAME; --purge-conda remove todo o Miniconda (com confirmação)

Variáveis via export:
  CONDADIR=/caminho       (default: \$HOME/miniconda3)
  APP_ENTRY=app.py        (default: app.py)
  RUN_SPADES_TEST=0|1     (default: 0)
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
    echo "[INFO] conda.sh não encontrado em $CONDADIR; tentando hook..."
    [[ -x "$CONDADIR/bin/conda" ]] || return 1
    "$CONDADIR/bin/conda" shell.bash hook >/dev/null 2>&1 || return 1
  }
}

ensure_miniconda() {
  if [[ ! -x "$CONDADIR/bin/conda" ]]; then
    echo "[INFO] instalando Miniconda em $CONDADIR..."
    local TMP="$HOME/Miniconda3-latest-Linux-$(uname -m).sh"
    # x86_64 e aarch64 cobertos; em outras arquit. aborta
    case "$(uname -m)" in
      x86_64|amd64)  curl -fsSL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -o "$TMP" ;;
      aarch64|arm64) curl -fsSL https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-aarch64.sh -o "$TMP" ;;
      *) echo "[ERRO] Arquitetura não suportada: $(uname -m)"; exit 1 ;;
    esac
    bash "$TMP" -b -p "$CONDADIR"
    rm -f "$TMP"
  fi
  load_conda || { echo "[ERRO] Não foi possível carregar o conda em $CONDADIR"; exit 1; }
}

env_exists() { conda env list | awk '{print $1}' | grep -qx "$ENV_NAME"; }

# Instalador robusto: tenta mamba (fora do env) -> fallback conda classic
safe_install_env() {
  # usa apenas os canais informados (evita repo.anaconda.com default)
  local OVERRIDE=(--override-channels "${CONDA_CHANNELS[@]}")
  if command -v mamba >/dev/null 2>&1; then
    # mamba diretamente no env (sem conda run)
    if mamba install -n "$ENV_NAME" -y "${OVERRIDE[@]}" "$@"; then
      return 0
    else
      echo "[WARN] mamba falhou; tentando conda --solver=classic..."
    fi
  fi
  conda install -n "$ENV_NAME" -y "${OVERRIDE[@]}" --solver=classic "$@"
}

# ==================== ACTIONS ===================
do_install() {
  ensure_apt_mins
  ensure_miniconda

  if env_exists; then
    echo "[OK] Ambiente $ENV_NAME já existe. Garantindo dependências..."
    safe_install_env "${CORE_PKGS[@]}" "${ASSEMBLY_PKGS[@]}" || {
      echo "[ERRO] Falha ao garantir pacotes no env $ENV_NAME"; exit 1; }
  else
    echo "[INFO] Criando ambiente $ENV_NAME..."
    # cria com mamba no pacote para acelerar próximas operações, mas a instalação em si usa conda classic se preciso
    conda create -y -n "$ENV_NAME" --override-channels "${CONDA_CHANNELS[@]}" mamba "${CORE_PKGS[@]}"
    safe_install_env "${ASSEMBLY_PKGS[@]}"
  fi

  mkdir -p fastp_output assemblies quast_reports

  cat <<MSG

###################### pronto! ######################
Ambiente:   $ENV_NAME
Ferramentas:
  - fastp, fastqc, multiqc
  - SPAdes (spades.py, metaspades.py, etc.)
  - Unicycler (unicycler)
  - QUAST (quast.py)

Tkinter:    incluído (pacote tk)

Para rodar sua GUI:
  source "$CONDADIR/etc/profile.d/conda.sh"
  conda activate $ENV_NAME
  python "$APP_ENTRY"

Ou sem ativar:
  conda run -n $ENV_NAME python "$APP_ENTRY"

Dicas rápidas:
  conda run -n $ENV_NAME spades.py -1 reads_1.fq.gz -2 reads_2.fq.gz -o assemblies/sample1
  conda run -n $ENV_NAME unicycler -1 short_1.fq.gz -2 short_2.fq.gz -l long_reads.fq.gz -o assemblies/sample1_unicycler
  conda run -n $ENV_NAME quast.py assemblies/sample1/contigs.fasta -o quast_reports/sample1
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

  conda run -n "$ENV_NAME" python -V || { echo "[FALHA] Python não acessível no env"; exit 2; }
  conda run -n "$ENV_NAME" bash -lc 'python - <<PY
import tkinter as tk
print("Tkinter OK, TkVersion=", tk.TkVersion)
PY' || { echo "[FALHA] Tkinter indisponível (pacote tk ausente?)"; exit 2; }

  conda run -n "$ENV_NAME" bash -lc 'command -v fastp >/dev/null && echo "[OK] fastp encontrado: $(fastp -v 2>&1 | head -n1)" || echo "[FALHA] fastp ausente"'
  conda run -n "$ENV_NAME" bash -lc 'command -v fastqc >/dev/null && echo "[OK] fastqc encontrado: $(fastqc -v 2>&1 | head -n1)" || echo "[AVISO] fastqc ausente (opcional)"'
  conda run -n "$ENV_NAME" bash -lc 'multiqc --version >/dev/null 2>&1 && echo "[OK] multiqc encontrado: $(multiqc --version)" || echo "[FALHA] multiqc ausente"'

  conda run -n "$ENV_NAME" bash -lc 'command -v spades.py >/dev/null && echo "[OK] SPAdes encontrado: $(spades.py --version 2>&1 | tr -d \"\r\" | head -n1)" || echo "[FALHA] SPAdes ausente"'
  conda run -n "$ENV_NAME" bash -lc 'command -v unicycler >/dev/null && echo "[OK] Unicycler encontrado: $(unicycler --version 2>&1 | head -n1)" || echo "[FALHA] Unicycler ausente"'
  conda run -n "$ENV_NAME" bash -lc 'command -v quast.py >/dev/null && echo "[OK] QUAST encontrado: $(quast.py --version 2>&1 | head -n1)" || echo "[FALHA] QUAST ausente"'

  if [[ "$RUN_SPADES_TEST" == "1" ]]; then
    echo "[INFO] Executando teste do SPAdes (spades.py --test)..."
    conda run -n "$ENV_NAME" spades.py --test >/dev/null
    echo "[OK] SPAdes test finalizado."
  fi

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

  echo "[INFO] Pastas de saída do usuário foram preservadas (ex.: fastp_output, assemblies, quast_reports)."

  if (( purge_conda )); then
    if [[ -x "$CONDADIR/bin/conda" ]]; then
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
