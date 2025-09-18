# ---------------------------
#Guardião do ambiente conda
# ---------------------------
import os, sys, shutil, subprocess, pathlib

ENV_NAME = "NB_HCPA_Workflow"

# Guardião do ambiente conda (_reexec_in_conda)
#    - Se o script NÃO estiver rodando no env alvo, ele se relança com:
#      "conda run -n NB_HCPA_Workflow python <este_arquivo.py>".
#    - Variável NB_PIPELINE_BOOTSTRAPPED evita loop de realimentação.
#    - Garante que fastp/multiqc/tkinter venham do ambiente correto.

def _reexec_in_conda():
    # Procura o executável do conda (variável CONDA_EXE, no PATH ou em ~/miniconda3/bin/conda).
    conda = os.environ.get("CONDA_EXE") or shutil.which("conda")
    if not conda:
        cand = pathlib.Path.home() / "miniconda3" / "bin" / "conda"
        conda = str(cand) if cand.exists() else None
    if not conda:
        sys.stderr.write(
            "[ERRO] Este programa deve rodar no ambiente conda '%s' e não encontrei o 'conda'.\n"
            "Instale/defina CONDADIR ou rode via: conda run -n %s python %s\n"
            % (ENV_NAME, ENV_NAME, sys.argv[0])
        )
        sys.exit(1)

    # evita loop infinito
    os.environ["NB_PIPELINE_BOOTSTRAPPED"] = "1"

    # reexecuta no ambiente correto
    os.execv(conda, ["conda", "run", "-n", ENV_NAME, "python", *sys.argv])

# ---------------------------
# Se já reentramos via conda.run, seguimos; caso contrário, garanta env correto
# ---------------------------
if os.environ.get("NB_PIPELINE_BOOTSTRAPPED") != "1":
    # se já estamos no env certo, ok; senão, reexecuta
    if os.environ.get("CONDA_DEFAULT_ENV") != ENV_NAME:
        # também tenta capturar erro típico: falta do tkinter no Python atual
        try:
            import tkinter  # noqa
        except Exception:
            _reexec_in_conda()
        else:
            # estamos fora do env e com tkinter disponível; mesmo assim, padronize no env
            _reexec_in_conda()

#você pode rodar python app.py de onde quiser; se não estiver no env NB_HCPA_Workflow, ele se relança sozinho no env certo TEORICAMENTE (desde que conda exista).

# ---------------------------
#IMPORTAÇÃO DE PACOTES PARA O AMBIENTE
# ---------------------------
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import subprocess
import os
import threading
import webbrowser
import shutil
import re
import shlex
from pathlib import Path
import signal
from queue import Queue, Empty
# ------------ Tema Azure: helpers ------------
from pathlib import Path
import sys

def resource_path(*parts) -> Path:
    """Caminho absoluto para recursos (funciona com PyInstaller)."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)

def load_azure_theme(tkroot, mode="dark"):
    """
    Carrega o Azure a partir de:
      ./azure.tcl
      ./theme/light.tcl, ./theme/dark.tcl
      ./azure/   (imagens)
    Alguns azure.tcl fazem 'source theme/light.tcl' -> garantimos o cwd do Tcl.
    """
    base      = resource_path()
    azure_tcl = base / "azure.tcl"
    light_tcl = base / "theme" / "light.tcl"
    dark_tcl  = base / "theme" / "dark.tcl"

    missing = [p for p in [azure_tcl, light_tcl, dark_tcl] if not p.exists()]
    if missing:
        msg = "Arquivos/pastas do tema ausentes:\n" + "\n".join(f" - {p}" for p in missing)
        messagebox.showerror("Tema Azure", msg)
        return

    old_pwd = tkroot.tk.call("pwd")
    try:
        # mude o cwd do Tcl para que 'source theme/*.tcl' funcione
        tkroot.tk.call("cd", base.as_posix())
        tkroot.tk.call("source", azure_tcl.as_posix())
        tkroot.tk.call("set_theme", mode)  # "dark" ou "light"
    finally:
        tkroot.tk.call("cd", old_pwd)

# ----- Fazer tk.* "herdar" as cores do tema (Text/Listbox/Canvas) -----
def _theme_colors():
    s = ttk.Style()
    theme = s.theme_use()
    bg = s.lookup("TFrame", "background") or s.lookup(".", "background") or "#202020"
    fg = s.lookup("TLabel", "foreground") or s.lookup(".", "foreground") or "#ffffff"
    sel_bg = s.lookup("Treeview", "selectbackground") or s.lookup("TEntry", "selectbackground") or "#2b6cb0"
    sel_fg = s.lookup("Treeview", "selectforeground") or s.lookup("TEntry", "selectforeground") or "#ffffff"
    insert = s.lookup("TEntry", "insertcolor") or fg
    if theme.endswith("light"):
        bg = bg or "#ffffff"
        fg = "#000000" if fg in ("", "#ffffff") else fg
        sel_bg = sel_bg or "#2563eb"
        sel_fg = sel_fg or "#ffffff"
        insert = insert or fg
    return {"bg": bg, "fg": fg, "sel_bg": sel_bg, "sel_fg": sel_fg, "insert": insert}

def apply_classic_defaults(root: tk.Misc):
    """Defaults globais para widgets clássicos criados daqui pra frente."""
    c = _theme_colors()
    root.option_add("*Background",         c["bg"])
    root.option_add("*Foreground",         c["fg"])
    root.option_add("*insertBackground",   c["insert"])
    root.option_add("*selectBackground",   c["sel_bg"])
    root.option_add("*selectForeground",   c["sel_fg"])
    root.option_add("*Text.background",    c["bg"])
    root.option_add("*Text.foreground",    c["fg"])
    root.option_add("*Listbox.background", c["bg"])
    root.option_add("*Listbox.foreground", c["fg"])
    root.option_add("*Canvas.background",  c["bg"])
    try:
        root.configure(bg=c["bg"])
    except tk.TclError:
        pass

def retint_classic_widgets(root: tk.Misc):
    """Recolore Text/Listbox/Canvas já existentes."""
    c = _theme_colors()
    def _paint(w):
        if isinstance(w, tk.Text):
            w.configure(bg=c["bg"], fg=c["fg"], insertbackground=c["insert"],
                        highlightthickness=0, relief="flat")
        elif isinstance(w, tk.Listbox):
            w.configure(bg=c["bg"], fg=c["fg"],
                        selectbackground=c["sel_bg"], selectforeground=c["sel_fg"],
                        highlightthickness=0, relief="flat")
        elif isinstance(w, tk.Canvas):
            w.configure(bg=c["bg"], highlightthickness=0)
        for child in w.winfo_children():
            _paint(child)
    _paint(root)




PAIR_REGEX = re.compile(r"(.+?)[._-]R?([12])(?:_001)?\.(?:fastq|fq)(?:\.gz)?$",re.IGNORECASE)


# Identifica FASTQs pareados (R1/R2), com ou sem compressão .gz
# Padrão: <prefixo>[._-]R?<1|2>[_001]?.<fastq|fq>[.gz]$
#
# Quebra da regex:
# (.+?)           -> GRUPO 1: prefixo da amostra (captura mínima até o separador)
# [._-]           -> separador permitido: ponto (.), underline (_) ou hífen (-)
# R?              -> 'R' opcional (aceita "R1"/"R2" ou só "1"/"2")
# ([12])          -> GRUPO 2: número da leitura (1 ou 2)
# (?:_001)?       -> sufixo opcional comum do bcl2fastq/DRAGEN
# \.              -> ponto literal antes da extensão
# (?:fastq|fq)    -> extensão base aceita
# (?:\.gz)?       -> compressão .gz opcional
# $               -> âncora de fim (garante que termina aqui)
# Flag: re.IGNORECASE -> case-insensitive (FASTQ, Fastq, etc.)
#
# Exemplos que CASAM:
#   SampleA_R1_001.fastq.gz  -> grp1='SampleA', grp2='1'
#   proj.subset-R2.fastq     -> grp1='proj.subset', grp2='2'
#   abc-1.fq.gz              -> grp1='abc', grp2='1'
#
# Exemplos que NÃO casam:
#   sample_R3.fastq.gz       -> apenas 1 ou 2 são válidos
#   sample_R1.fastq.bz2      -> só .gz (ou nada) é aceito
#   sample R1.fastq          -> separador deve ser ., _ ou -
#
# Uso:
# m = PAIR_REGEX.search(path)
# if m:
#     sample, read = m.group(1), m.group(2)






# Define absolute output directory
BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "fastp_output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

def _abs(p):
    return str((OUT_DIR / p).resolve())

# ---------------------------
# APLICAÇÃO PRINCIPAL
# ---------------------------
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        load_azure_theme(self, mode="dark")
        apply_classic_defaults(self)   # para tk.*

        self.title("NB_HCPA Workflow")

        
        try:
            self.attributes('-zoomed', True)
        except Exception:
            self.state('zoomed')

        # Ajuste aqui se o nome do ambiente mudar #
        self.env_name = "NB_HCPA_Workflow"

        # Fila para logs thread-safe
        self._log_queue = Queue()
        self.after(100, self._flush_logs)

# Controle de subprocesso: self.current_proc / self.stop_requested / self.batch_proc
#    - self.current_proc guarda o objeto subprocess.Popen do fastp em execução.
#    - self.stop_requested é uma flag booleana: quando True, a thread de leitura
#      de stdout tenta encerrar o processo (SIGTERM no grupo, ou terminate()).
#    - Em Unix, preexec_fn=os.setsid cria um *grupo de processos*; isso permite
#      matar todo o grupo (fastp + filhos) com os.killpg(..., SIGTERM).
#    - O laço de leitura usa readline() em stdout para *streaming* de linhas:
#      cada linha é enviada para a fila de logs (Queue) e então exibida pela GUI.
#    - Ao terminar, wait() é chamado, e self.current_proc volta a None.
#    - self.batch_proc está reservado para fluxos em lote (não utilizado aqui)


        # Controle de processos
        self.current_proc = None
        self.stop_requested = False
        self.batch_proc = None

        # Notebook
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill='both', expand=True)


        # Abas
        self.create_filtering_tab()   # fastp (única aba de processamento)
        self.create_cleanup_tab()     # limpeza

        retint_classic_widgets(self)

        # Verificações
        self.check_environment()
        self.check_required_tools(["fastp", "multiqc"])

    # ---------------------------
    # Helpers: env + command exec
    # ---------------------------
    def activate_env_command(self, command: str) -> str:
        """Prefer conda run when available; fallback to bash+source."""
        return f"conda run -n {self.env_name} bash -lc {shlex.quote(command)}"

    def tool_exists(self, tool: str) -> bool:
        try:
            cmd = self.activate_env_command(
                f"command -v {shlex.quote(tool)} >/dev/null 2>&1 && echo OK || echo MISSING"
            )
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=True)
            return "OK" in res.stdout
        except Exception:
            return False

    def check_required_tools(self, tools):
        missing = [t for t in tools if not self.tool_exists(t)]
        if missing:
            lista = "\n- ".join(missing)
            msg = (
                f"As seguintes ferramentas não foram encontradas no ambiente "
                f"'{self.env_name}':\n- {lista}\n\n"
                "Instale-as (ex.: conda install -c bioconda <tool>) e tente novamente."
            )
            self.show_message_popup("Ferramentas ausentes", msg)

    def check_environment(self):
        try:
            result = subprocess.run(
                self.activate_env_command("echo $CONDA_DEFAULT_ENV"),
                shell=True, capture_output=True, text=True, check=True
            )
            if self.env_name in result.stdout:
                self.show_env_popup("Ambiente Verificado", f"Environment '{self.env_name}' is active.")
            else:
                raise ValueError("Environment not active.")
        except Exception as e:
            self.show_env_popup("Erro ao Verificar Ambiente", str(e))

    def make_vertical_scroller(self, parent):
        container = ttk.Frame(parent)
        canvas = tk.Canvas(container, highlightthickness=0)
        vscroll = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)

        # Ajusta a área rolável ao tamanho do conteúdo:
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        # Faz o inner ter sempre a mesma largura do canvas:
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure("inner", width=e.width))

        # Cria a janela que mostrará o frame interno
        canvas_window = canvas.create_window((0, 0), window=inner, anchor="nw", tags=("inner",))

        canvas.configure(yscrollcommand=vscroll.set)

        # Layout
        canvas.pack(side="left", fill="both", expand=True)
        vscroll.pack(side="right", fill="y")
        container.pack(fill="both", expand=True)

        # Suporte ao scroll do mouse (Windows/macOS/Linux)
        def _on_mousewheel(event):
            if event.num == 4:     # Linux scroll up
                canvas.yview_scroll(-1, "units")
            elif event.num == 5:   # Linux scroll down
                canvas.yview_scroll(1, "units")
            else:                  # Windows/macOS
                delta = int(-1*(event.delta/120))
                canvas.yview_scroll(delta, "units")

        # Ativa/desativa o binding quando o mouse entra/sai do container
        container.bind("<Enter>", lambda e: (
            container.bind_all("<MouseWheel>", _on_mousewheel),
            container.bind_all("<Button-4>", _on_mousewheel),
            container.bind_all("<Button-5>", _on_mousewheel),
        ))
        container.bind("<Leave>", lambda e: (
            container.unbind_all("<MouseWheel>"),
            container.unbind_all("<Button-4>"),
            container.unbind_all("<Button-5>"),
        ))

        return container, inner, canvas


    # ---------------------------
    # Logging a partir de threads
    # ---------------------------
    def log(self, widget: tk.Text, text: str):
        self._log_queue.put((widget, text))

    def _flush_logs(self):
        try:
            while True:
                widget, text = self._log_queue.get_nowait()
                if widget and widget.winfo_exists():
                    widget.insert(tk.END, text)
                    widget.see(tk.END)
        except Empty:
            pass
        self.after(100, self._flush_logs)

    def _ui(self, fn, *args, **kwargs):
        self.after(0, lambda: fn(*args, **kwargs))

    # ===============================
    # Aba: Filtragem + Relatórios (fastp)
    # ===============================
    def create_filtering_tab(self):
        # Cria UMA aba
        holder = ttk.Frame(self.notebook)
        self.notebook.add(holder, text="fastp — Filtragem e Relatórios")

        # Cria o scroller dentro da aba e usa o 'inner' como parent de tudo
        _container, self.filtering_frame, _canvas = self.make_vertical_scroller(holder)

        # Configuração de grid do frame rolável
        self.filtering_frame.columnconfigure(0, weight=1)
        self.filtering_frame.rowconfigure(3, weight=1)


        # Cabeçalho
        header = ttk.Frame(self.filtering_frame)
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=6)
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="Pré-processamento e QC com fastp").grid(row=0, column=0, sticky="w")
        ttk.Button(header, text="?", width=3, command=self.show_fastp_help).grid(row=0, column=1, sticky="e")
        ttk.Button(header, text="Tema", command=self.toggle_theme, style="Accent.TButton").grid(row=0, column=2, sticky="e", padx=6)

        # 1) Seleção de arquivos
        file_sel_frame, self.fastp_file_listbox = self.create_file_selection_frame(self.filtering_frame)
        file_sel_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=6)

        # 2) Parâmetros principais
        main = ttk.LabelFrame(self.filtering_frame, text="Parâmetros principais")
        main.grid(row=2, column=0, sticky="nsew", padx=8, pady=6)
        for c in range(8):
            main.columnconfigure(c, weight=1)

        # Modo: manual (PE ou SE) — removido AUTO
        self.seq_mode = tk.StringVar(value="PE")  # PE por padrão
        ttk.Label(main, text="Modo de leitura").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self.mode_combo = ttk.Combobox(
            main, textvariable=self.seq_mode, width=10, state="readonly", values=["PE", "SE"]
        )
        self.mode_combo.grid(row=0, column=1, sticky="w")
        self.mode_combo.set("PE")

        # Threads
        ttk.Label(main, text="Threads (-w)").grid(row=0, column=3, sticky="w", padx=4)
        self.threads = tk.IntVar(value=4)
        ttk.Spinbox(main, from_=1, to=128, textvariable=self.threads, width=6).grid(row=0, column=4, sticky="w")

        # Overwrite
        self.dont_overwrite = tk.BooleanVar(value=False)
        ttk.Checkbutton(main, text="Não sobrescrever (--dont_overwrite)", variable=self.dont_overwrite).grid(row=0, column=5, sticky="w")

        # Somente relatório (sem cortes/saídas)
        self.only_report = tk.BooleanVar(value=False)
        ttk.Checkbutton(main, text="Somente relatório (sem cortes/sem saída)", variable=self.only_report).grid(row=0, column=6, sticky="w")

        # Qualidade e comprimento
        ttk.Label(main, text="Qualidade mínima qualificada (-q)").grid(row=1, column=0, sticky="w", padx=4, pady=4)
        self.qualified_quality_phred = tk.IntVar(value=15)
        ttk.Entry(main, textvariable=self.qualified_quality_phred, width=6).grid(row=1, column=1, sticky="w")

        ttk.Label(main, text="% não qualificado (-u)").grid(row=1, column=2, sticky="w", padx=4)
        self.unqualified_percent_limit = tk.IntVar(value=40)
        ttk.Entry(main, textvariable=self.unqualified_percent_limit, width=6).grid(row=1, column=3, sticky="w")

        ttk.Label(main, text="N base limit (-n)").grid(row=1, column=4, sticky="w", padx=4)
        self.n_base_limit = tk.IntVar(value=5)
        ttk.Entry(main, textvariable=self.n_base_limit, width=6).grid(row=1, column=5, sticky="w")

        ttk.Label(main, text="Comprimento mínimo (-l)").grid(row=2, column=0, sticky="w", padx=4)
        self.min_length = tk.IntVar(value=50)
        ttk.Entry(main, textvariable=self.min_length, width=6).grid(row=2, column=1, sticky="w")

        ttk.Label(main, text="Comprimento máximo (--length_limit)").grid(row=2, column=2, sticky="w", padx=4)
        self.length_limit = tk.IntVar(value=0)
        ttk.Entry(main, textvariable=self.length_limit, width=6).grid(row=2, column=3, sticky="w")

        # Opções específicas úteis conforme documentação fastp
        adv2 = ttk.LabelFrame(self.filtering_frame, text="Opções específicas (PE)")
        adv2.grid(row=3, column=0, sticky="nsew", padx=8, pady=6)
        for c in range(6):
            adv2.columnconfigure(c, weight=1)
        self.detect_adapter_for_pe = tk.BooleanVar(value=False)
        ttk.Checkbutton(adv2, text="Detectar adaptador PE (--detect_adapter_for_pe)", variable=self.detect_adapter_for_pe).grid(row=0, column=0, sticky="w")
        self.enable_correction = tk.BooleanVar(value=False)
        ttk.Checkbutton(adv2, text="Correção por overlap (-c/--correction)", variable=self.enable_correction).grid(row=0, column=1, sticky="w")

        # Sliding window
        slide = ttk.LabelFrame(self.filtering_frame, text="Corte por qualidade (sliding window)")
        slide.grid(row=4, column=0, sticky="nsew", padx=8, pady=6)
        for c in range(7):
            slide.columnconfigure(c, weight=1)

        self.cut_front = tk.BooleanVar(value=True)
        self.cut_tail = tk.BooleanVar(value=True)
        self.cut_right = tk.BooleanVar(value=False)
        ttk.Checkbutton(slide, text="cut_front (-5)", variable=self.cut_front).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(slide, text="cut_tail (-3)", variable=self.cut_tail).grid(row=0, column=1, sticky="w")
        ttk.Checkbutton(slide, text="cut_right (-r)", variable=self.cut_right).grid(row=0, column=2, sticky="w")

        ttk.Label(slide, text="Window size (-W)").grid(row=0, column=3, sticky="e")
        self.cut_window_size = tk.IntVar(value=4)
        ttk.Entry(slide, textvariable=self.cut_window_size, width=6).grid(row=0, column=4, sticky="w")

        ttk.Label(slide, text="Mean quality (-M)").grid(row=0, column=5, sticky="e")
        self.cut_mean_quality = tk.IntVar(value=20)
        ttk.Entry(slide, textvariable=self.cut_mean_quality, width=6).grid(row=0, column=6, sticky="w")

        # Global trimming
        gtrim = ttk.LabelFrame(self.filtering_frame, text="Global trimming")
        gtrim.grid(row=5, column=0, sticky="nsew", padx=8, pady=6)
        for c in range(6):
            gtrim.columnconfigure(c, weight=1)

        ttk.Label(gtrim, text="trim_front1 (-f)").grid(row=0, column=0, sticky="w")
        self.trim_front1 = tk.IntVar(value=0)
        ttk.Entry(gtrim, textvariable=self.trim_front1, width=6).grid(row=0, column=1, sticky="w")

        ttk.Label(gtrim, text="trim_tail1 (-t)").grid(row=0, column=2, sticky="w")
        self.trim_tail1 = tk.IntVar(value=0)
        ttk.Entry(gtrim, textvariable=self.trim_tail1, width=6).grid(row=0, column=3, sticky="w")

        ttk.Label(gtrim, text="max_len1 (-b)").grid(row=0, column=4, sticky="w")
        self.max_len1 = tk.IntVar(value=0)
        ttk.Entry(gtrim, textvariable=self.max_len1, width=6).grid(row=0, column=5, sticky="w")

        ttk.Label(gtrim, text="trim_front2 (-F)").grid(row=1, column=0, sticky="w")
        self.trim_front2 = tk.IntVar(value=0)
        ttk.Entry(gtrim, textvariable=self.trim_front2, width=6).grid(row=1, column=1, sticky="w")

        ttk.Label(gtrim, text="trim_tail2 (-T)").grid(row=1, column=2, sticky="w")
        self.trim_tail2 = tk.IntVar(value=0)
        ttk.Entry(gtrim, textvariable=self.trim_tail2, width=6).grid(row=1, column=3, sticky="w")

        ttk.Label(gtrim, text="max_len2 (-B)").grid(row=1, column=4, sticky="w")
        self.max_len2 = tk.IntVar(value=0)
        ttk.Entry(gtrim, textvariable=self.max_len2, width=6).grid(row=1, column=5, sticky="w")

        # Adaptadores e opções diversas
        adv = ttk.LabelFrame(self.filtering_frame, text="Opções adicionais")
        adv.grid(row=6, column=0, sticky="nsew", padx=8, pady=6)
        for c in range(8):
            adv.columnconfigure(c, weight=1)

        ttk.Label(adv, text="adapter R1 (-a)").grid(row=0, column=0, sticky="w")
        self.adapter_sequence = tk.StringVar(value="auto")
        ttk.Entry(adv, textvariable=self.adapter_sequence).grid(row=0, column=1, sticky="ew")

        ttk.Label(adv, text="adapter R2 (--adapter_sequence_r2)").grid(row=0, column=2, sticky="w")
        self.adapter_sequence_r2 = tk.StringVar(value="")
        ttk.Entry(adv, textvariable=self.adapter_sequence_r2).grid(row=0, column=3, sticky="ew")

        # Split de saída para paralelização downstream
        ttk.Label(adv, text="Split por nº arquivos (-s)").grid(row=1, column=0, sticky="w")
        self.split_files = tk.IntVar(value=0)
        ttk.Entry(adv, textvariable=self.split_files, width=8).grid(row=1, column=1, sticky="w")

        ttk.Label(adv, text="Split por linhas (-S)").grid(row=1, column=2, sticky="w")
        self.split_by_lines = tk.IntVar(value=0)
        ttk.Entry(adv, textvariable=self.split_by_lines, width=10).grid(row=1, column=3, sticky="w")

        ttk.Label(adv, text="Prefix digits (-d)").grid(row=1, column=4, sticky="w")
        self.split_prefix_digits = tk.IntVar(value=4)
        ttk.Entry(adv, textvariable=self.split_prefix_digits, width=6).grid(row=1, column=5, sticky="w")

        # Botões de execução
        btns = ttk.Frame(self.filtering_frame)
        btns.grid(row=7, column=0, sticky="ew", padx=8, pady=6)
        ttk.Button(btns, text="Rodar fastp", command=self.run_fastp_thread).pack(side="left")
        ttk.Button(btns, text="Interromper", command=self.stop_fastp).pack(side="left", padx=6)
        ttk.Button(btns, text="Atualizar relatórios", command=self.update_reports_list).pack(side="left", padx=6)

        # Saída de log
        self.fastp_output_text = tk.Text(self.filtering_frame, wrap="word", height=12)
        self.fastp_output_text.grid(row=8, column=0, sticky="nsew", padx=8, pady=6)

        # Lista de relatórios HTML do fastp
        rep = ttk.LabelFrame(self.filtering_frame, text="Relatórios HTML (fastp_output)")
        rep.grid(row=9, column=0, sticky="nsew", padx=8, pady=6)
        rep.columnconfigure(0, weight=1)
        rep.rowconfigure(0, weight=1)

        self.reports_listbox = tk.Listbox(rep, height=8, selectmode="extended")
        self.reports_listbox.grid(row=0, column=0, sticky="nsew")
        rep_scroll = ttk.Scrollbar(rep, orient="vertical", command=self.reports_listbox.yview)
        rep_scroll.grid(row=0, column=1, sticky="ns")
        self.reports_listbox.configure(yscrollcommand=rep_scroll.set)

        rep_btns = ttk.Frame(rep)
        rep_btns.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        ttk.Button(rep_btns, text="Abrir selecionado(s)", command=self.open_report).pack(side="left")
        ttk.Button(rep_btns, text="Atualizar lista", command=self.update_reports_list).pack(side="left", padx=6)
        ttk.Button(rep_btns, text="Gerar MultiQC", command=self.run_multiqc_thread).pack(side="left", padx=6)

    # ===============================
    # Execução fastp
    # ===============================
    def run_fastp_thread(self):
        def target():
            try:
                self.run_fastp_analysis()
            finally:
                self._ui(self._set_running, False)
        self._set_running(True)
        threading.Thread(target=target, daemon=True).start()

    def _set_running(self, running: bool):
        # desabilita / habilita botões na aba
        for child in self.filtering_frame.winfo_children():
            if isinstance(child, ttk.Button):
                try:
                    child.state(["disabled"] if running else ["!disabled"])
                except Exception:
                    pass

    def _build_common_fastp_parts(self, report_html, report_json):
        parts = ["fastp"]

        # Threads
        parts += ["-w", str(self.threads.get())]

        # Overwrite
        if self.dont_overwrite.get():
            parts += ["--dont_overwrite"]

        # Sempre adiciona os relatórios
        parts += ["-j", report_json, "-h", report_html]

        # Somente relatório: desabilita filtros/trims/polyg e não adiciona cortes
        if self.only_report.get():
            parts += ["-A", "-Q", "-L", "-G"]
            return parts

        # Caso normal: Qualidade & comprimento
        parts += [
            "-q", str(self.qualified_quality_phred.get()),
            "-u", str(self.unqualified_percent_limit.get()),
            "-n", str(self.n_base_limit.get()),
            "-l", str(self.min_length.get()),
        ]
        if self.length_limit.get() > 0:
            parts += ["--length_limit", str(self.length_limit.get())]

        # Sliding window (definir -W/-M apenas uma vez, conforme doc)
        need_sw = self.cut_front.get() or self.cut_tail.get() or self.cut_right.get()
        if self.cut_front.get():
            parts += ["-5"]
        if self.cut_tail.get():
            parts += ["-3"]
        if self.cut_right.get():
            parts += ["-r"]
        if need_sw:
            parts += ["-W", str(self.cut_window_size.get()), "-M", str(self.cut_mean_quality.get())]

        # Global trimming
        if self.trim_front1.get():
            parts += ["-f", str(self.trim_front1.get())]
        if self.trim_tail1.get():
            parts += ["-t", str(self.trim_tail1.get())]
        if self.max_len1.get():
            parts += ["-b", str(self.max_len1.get())]
        if self.trim_front2.get():
            parts += ["-F", str(self.trim_front2.get())]
        if self.trim_tail2.get():
            parts += ["-T", str(self.trim_tail2.get())]
        if self.max_len2.get():
            parts += ["-B", str(self.max_len2.get())]

        # Adapters
        if self.seq_mode.get() == "PE" and self.detect_adapter_for_pe.get():
            parts += ["--detect_adapter_for_pe"]
        if self.adapter_sequence.get():
            parts += ["-a", self.adapter_sequence.get()]
        if self.adapter_sequence_r2.get():
            parts += ["--adapter_sequence_r2", self.adapter_sequence_r2.get()]

        # Splitting (mutuamente exclusivos)
        if self.split_files.get() and self.split_by_lines.get():
            self.log(self.fastp_output_text, "[Aviso] Use apenas -s ou -S (um tipo de split por vez)\n")
        elif self.split_files.get():
            parts += ["-s", str(self.split_files.get()), "-d", str(self.split_prefix_digits.get())]
        elif self.split_by_lines.get():
            parts += ["-S", str(self.split_by_lines.get()), "-d", str(self.split_prefix_digits.get())]

        # Correção por overlap (PE)
        if self.seq_mode.get() == "PE" and self.enable_correction.get():
            parts += ["-c"]

        return parts

    def _pair_key_and_read(self, filepath: str):
        """Return (key, read) where read is 1 or 2 if pattern matches; else (None, None)."""
        m = PAIR_REGEX.search(os.path.basename(filepath))
        if not m:
            return None, None
        key = m.group(1)
        read = int(m.group(2))
        return key, read

    def _detect_pairs(self, files):
        pairs = []
        r1_only = []
        r2_only = []
        unknown = []
        bucket = {}
        for f in files:
            key, read = self._pair_key_and_read(f)
            if key is None:
                unknown.append(f)
                continue
            d = bucket.setdefault(key, {})
            d[read] = f
        for key, d in bucket.items():
            if 1 in d and 2 in d:
                pairs.append((d[1], d[2], key))
            elif 1 in d:
                r1_only.append(d[1])
            elif 2 in d:
                r2_only.append(d[2])
        return pairs, r1_only, r2_only, unknown

    def run_fastp_analysis(self):
        files = list(self.fastp_file_listbox.get(0, tk.END))
        if not files:
            self._ui(messagebox.showerror, "Erro", "Nenhum arquivo selecionado para filtragem.")
            return

        output_dir = OUT_DIR  # Use absolute output dir
        output_dir.mkdir(parents=True, exist_ok=True)
        self._ui(self.fastp_output_text.delete, 1.0, tk.END)
        processed_files = []

        mode = (self.seq_mode.get() or "PE").upper()
        self.stop_requested = False

        def run_pe(file_r1, file_r2, base_key):
            base_name = base_key
            out_r1 = output_dir / f"{base_name}_R1_cleaned.fastq.gz"
            out_r2 = output_dir / f"{base_name}_R2_cleaned.fastq.gz"
            report_html = _abs(f"{base_name}_fastp_report.html")
            report_json = _abs(f"{base_name}_fastp_report.json")
            failed_out = os.devnull
            # Log CWD and report paths for diagnostics
            self.log(self.fastp_output_text, f"CWD: {os.getcwd()}\n")
            self.log(self.fastp_output_text, f"HTML: {report_html}\nJSON: {report_json}\n")
            parts = self._build_common_fastp_parts(report_html, report_json)
            parts += ["-i", file_r1, "-I", file_r2]
            if not self.only_report.get():
                parts += ["-o", str(out_r1), "-O", str(out_r2), "--failed_out", failed_out]
            cmd = self.activate_env_command(" ".join(shlex.quote(p) for p in parts))
            self.log(self.fastp_output_text, f"Filtrando (PE): {file_r1} + {file_r2}\n")
            return cmd, [str(out_r1), str(out_r2)]

        def run_se(file_se):
            base = os.path.basename(file_se)
            base_name = re.sub(r"\.(fastq|fq)(?:\.gz)?$", "", base, flags=re.IGNORECASE)
            out1 = output_dir / f"{base_name}_cleaned.fastq.gz"
            report_html = _abs(f"{base_name}_fastp_report.html")
            report_json = _abs(f"{base_name}_fastp_report.json")
            failed_out = os.devnull
            # Log CWD and report paths for diagnostics
            self.log(self.fastp_output_text, f"CWD: {os.getcwd()}\n")
            self.log(self.fastp_output_text, f"HTML: {report_html}\nJSON: {report_json}\n")
            parts = self._build_common_fastp_parts(report_html, report_json)
            parts += ["-i", file_se]
            if not self.only_report.get():
                parts += ["-o", str(out1), "--failed_out", failed_out]
            cmd = self.activate_env_command(" ".join(shlex.quote(p) for p in parts))
            self.log(self.fastp_output_text, f"Filtrando (SE): {file_se}\n")
            return cmd, [str(out1)]

        def run_and_stream(cmd):
            try:
                self.current_proc = subprocess.Popen(
                    cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                    preexec_fn=os.setsid if hasattr(os, "setsid") else None, bufsize=1
                )
                for line in iter(self.current_proc.stdout.readline, ''):
                    if line:
                        self.log(self.fastp_output_text, line)
                    if self.stop_requested and self.current_proc and self.current_proc.poll() is None:
                        try:
                            if hasattr(os, "setsid"):
                                os.killpg(os.getpgid(self.current_proc.pid), signal.SIGTERM)
                            else:
                                self.current_proc.terminate()
                        except Exception:
                            pass
                        self.log(self.fastp_output_text, "[Interrompido pelo usuário]\n")
                        break
                ret = self.current_proc.wait()
                self.current_proc = None
                return ret
            except Exception as e:
                self.log(self.fastp_output_text, f"Erro inesperado: {e}\n")
                return -1

        # Loop de execução conforme modo
        if mode == "PE":
            pairs, r1_only, r2_only, unknown = self._detect_pairs(files)
            if r1_only:
                self.log(self.fastp_output_text, f"[Aviso] R1 sem par detectado: {len(r1_only)} arquivo(s). Serão ignorados no modo PE.\n")
            if r2_only:
                self.log(self.fastp_output_text, f"[Aviso] R2 sem par detectado: {len(r2_only)} arquivo(s). Serão ignorados no modo PE.\n")
            if unknown:
                self.log(self.fastp_output_text, f"[Aviso] Arquivo(s) com nome não reconhecido para PE: {len(unknown)}. Serão ignorados no modo PE.\n")

            for r1, r2, key in pairs:
                if self.stop_requested:
                    break
                cmd, outs = run_pe(r1, r2, key)
                ret = run_and_stream(cmd)
                if ret == 0 and not self.stop_requested:
                    self.log(self.fastp_output_text, "Concluído.\n")
                    if not self.only_report.get():
                        processed_files.extend(outs)
                elif ret != 0 and not self.stop_requested:
                    self.log(self.fastp_output_text, "Erro ao processar par.\n")

        else:  # SE
            for file in files:
                if self.stop_requested:
                    break
                cmd, outs = run_se(file)
                ret = run_and_stream(cmd)
                if ret == 0 and not self.stop_requested:
                    self.log(self.fastp_output_text, "Concluído.\n")
                    if not self.only_report.get():
                        processed_files.extend(outs)
                elif ret != 0 and not self.stop_requested:
                    self.log(self.fastp_output_text, "Erro ao processar arquivo.\n")

        if self.stop_requested:
            self.log(self.fastp_output_text, "Processamento interrompido.\n")
        else:
            self.log(self.fastp_output_text, "Processamento concluído!\n")

        # (Comentado) Adiciona arquivos processados à lista, se ainda não estiverem presentes
        # for f in processed_files:
        #     if f not in self.fastp_file_listbox.get(0, tk.END):
        #         self._ui(self.fastp_file_listbox.insert, 'end', f)
        self.update_reports_list()

    def stop_fastp(self):
        self.stop_requested = True
        if self.current_proc and self.current_proc.poll() is None:
            try:
                if hasattr(os, "setsid"):
                    os.killpg(os.getpgid(self.current_proc.pid), signal.SIGTERM)
                else:
                    self.current_proc.terminate()
            except Exception:
                pass

    def run_multiqc_thread(self):
        def target():
            try:
                self.run_multiqc()
            finally:
                self._ui(self._set_running, False)
        self._set_running(True)
        threading.Thread(target=target, daemon=True).start()

    def run_multiqc(self):
        outdir = OUT_DIR
        outdir.mkdir(parents=True, exist_ok=True)
        # Instala automaticamente o multiqc se não estiver presente
        if not self.tool_exists("multiqc"):
            self.log(self.fastp_output_text, "[MultiQC] 'multiqc' não encontrado. Instalando no ambiente...\n")
            install_cmd = self.activate_env_command("mamba install -y -c bioconda -c conda-forge multiqc || conda install -y -c bioconda -c conda-forge multiqc")
            proc_i = subprocess.run(install_cmd, shell=True, capture_output=True, text=True)
            if proc_i.stdout: self.log(self.fastp_output_text, proc_i.stdout)
            if proc_i.stderr: self.log(self.fastp_output_text, proc_i.stderr)
            if not self.tool_exists("multiqc"):
                self.log(self.fastp_output_text, "[MultiQC] Falha ao instalar automaticamente. Instale manualmente e tente de novo.\n")
                return
        cmd = self.activate_env_command(
            f"multiqc -f -o {shlex.quote(str(outdir))} {shlex.quote(str(outdir))}"
        )
        self.log(self.fastp_output_text, f"[MultiQC] Executando em: {outdir}\n")
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if proc.stdout: self.log(self.fastp_output_text, proc.stdout)
        if proc.stderr: self.log(self.fastp_output_text, proc.stderr)
        if proc.returncode == 0:
            self.log(self.fastp_output_text, "[MultiQC] Relatório gerado com sucesso.\n")
        else:
            self.log(self.fastp_output_text, "[MultiQC] ERRO ao gerar relatório.\n")
        self.update_reports_list()

    def update_reports_list(self):
        self.reports_listbox.delete(0, tk.END)
        out = OUT_DIR  # use the absolute output directory
        if out.exists():
            for file in sorted(out.glob("*_fastp_report.html")):
                self.reports_listbox.insert('end', str(file))
            mqc = out / "multiqc_report.html"
            if mqc.exists():
                self.reports_listbox.insert('end', str(mqc))

    def open_report(self):
        sel = self.reports_listbox.curselection()
        if not sel:
            messagebox.showwarning("Aviso", "Nenhum relatório selecionado.")
            return
        for i in sel:
            p = self.reports_listbox.get(i)
            webbrowser.open_new_tab(f"file://{Path(p).resolve()}")

    # ===============================
    # Ajuda do fastp
    # ===============================
    def show_fastp_help(self):
        help_text = (
            "fastp — Pré-processamento e QC de FASTQ\n\n"
            "• SE/PE manuais, threads (-w), split (-s/-S/-d), não sobrescrever,\n"
            "• Cortes por qualidade (-5/-3/-r com -W/-M), trimming global (-f/-t/-b/-F/-T/-B),\n"
            "• Filtros (-q/-u/-n, -l, --length_limit), adapters (-a/--adapter_sequence_r2, --detect_adapter_for_pe),\n"
            "• Correção por overlap (-c), Relatórios HTML/JSON (-h/-j).\n\n"
            "Modo 'Somente relatório' desativa trims/filtros (-A -Q -L -G) e não grava FASTQ."
        )
        win = tk.Toplevel(self)
        win.title("Ajuda - fastp")
        win.geometry("700x480")
        txt = tk.Text(win, wrap="word")
        txt.insert("1.0", help_text)
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        sb = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        sb.pack(side="right", fill="y")
        txt.configure(yscrollcommand=sb.set)

    # ===============================
    # Área comum: seleção de arquivos
    # ===============================
    def create_file_selection_frame(self, parent):
        frame = ttk.Frame(parent)
        frame.columnconfigure(0, weight=1)
        ttk.Label(
            frame,
            text="Selecione arquivos ou pastas contendo .fastq / .fq (com ou sem .gz):"
        ).grid(row=0, column=0, columnspan=3, padx=8, pady=4, sticky="w")

        listbox_frame = ttk.Frame(frame)
        listbox_frame.grid(row=1, column=0, columnspan=3, padx=8, pady=4, sticky="nsew")
        listbox_frame.columnconfigure(0, weight=1)
        listbox_frame.rowconfigure(0, weight=1)
        listbox = tk.Listbox(listbox_frame, selectmode="extended")
        listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar_y = ttk.Scrollbar(listbox_frame, orient="vertical", command=listbox.yview)
        scrollbar_y.grid(row=0, column=1, sticky="ns")
        listbox.configure(yscrollcommand=scrollbar_y.set)

        ttk.Button(frame, text="Adicionar Arquivos", command=lambda: self.add_files(listbox)).grid(row=2, column=0, padx=5, pady=5, sticky="w")
        ttk.Button(frame, text="Adicionar Pasta", command=lambda: self.add_folder(listbox)).grid(row=2, column=1, padx=5, pady=5, sticky="w")
        ttk.Button(frame, text="Remover Selecionado", command=lambda: self.remove_selected_file(listbox)).grid(row=2, column=2, padx=5, pady=5, sticky="w")
        return frame, listbox

    # ===============================
    # Aba: Limpeza
    # ===============================
    def create_cleanup_tab(self):
        self.cleanup_frame = ttk.Frame(self.notebook)
        self.notebook.add(self.cleanup_frame, text="Limpar Pastas")

        ttk.Label(self.cleanup_frame, text="Clique para limpar as pastas de saída:").grid(row=0, column=0, padx=10, pady=10, sticky="w")
        ttk.Button(self.cleanup_frame, text="Limpar Pastas de Output", command=self.cleanup_output_folders).grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.cleanup_status_label = ttk.Label(self.cleanup_frame, text="")
        self.cleanup_status_label.grid(row=2, column=0, padx=10, pady=10, sticky="w")

    def cleanup_output_folders(self):
        output_dirs = ["fastp_output", "kraken2_output"]
        try:
            for directory in output_dirs:
                d = Path(directory)
                if d.exists():
                    shutil.rmtree(d)
                d.mkdir(parents=True, exist_ok=True)
            self.cleanup_status_label.config(text="Pastas de output limpas com sucesso!", foreground="green")
        except Exception as e:
            self.cleanup_status_label.config(text=f"Erro ao limpar pastas: {e}", foreground="red")

    # ===============================
    # Utilitários
    # ===============================
    def show_env_popup(self, title, message):
        popup = tk.Toplevel(self)
        popup.title(title)
        popup.geometry("400x200")
        ttk.Label(popup, text=message, wraplength=350).pack(pady=10, padx=10)
        ttk.Button(popup, text="Fechar", command=popup.destroy).pack(pady=10)

    def show_message_popup(self, title, message):
        popup = tk.Toplevel(self)
        popup.title(title)
        popup.geometry("400x200")
        ttk.Label(popup, text=message, wraplength=350).pack(pady=10, padx=10)
        ttk.Button(popup, text="Fechar", command=popup.destroy).pack(pady=10)

    def add_files(self, listbox):
        initial_dir = os.getcwd()
        files = filedialog.askopenfilenames(
            filetypes=[
                ("Arquivos FASTQ", ("*.fastq", "*.fq", "*.fastq.gz", "*.fq.gz")),
                ("Todos os arquivos", "*.*"),
            ],
            initialdir=initial_dir,
        )
        existing = set(listbox.get(0, tk.END))
        for file in files:
            if file not in existing:
                listbox.insert('end', file)

    def add_folder(self, listbox):
        folder = filedialog.askdirectory()
        if not folder:
            return
        patterns = ["*.fastq", "*.fq", "*.fastq.gz", "*.fq.gz"]
        seen = set(listbox.get(0, tk.END))
        for pat in patterns:
            for path in sorted(Path(folder).rglob(pat)):
                s = str(path)
                if s not in seen:
                    listbox.insert('end', s)
                    seen.add(s)

    def remove_selected_file(self, listbox):
        selected_indices = listbox.curselection()
        for index in reversed(selected_indices):
            listbox.delete(index)

    def toggle_theme(self):
        cur = self.tk.call("ttk::style", "theme", "use")
        self.tk.call("set_theme", "light" if cur == "azure-dark" else "dark")
        apply_classic_defaults(self)
        retint_classic_widgets(self)


if __name__ == "__main__":
    app = App()
    app.mainloop()
