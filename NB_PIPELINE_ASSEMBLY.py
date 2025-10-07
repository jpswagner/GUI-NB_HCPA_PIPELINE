#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, shutil, subprocess, pathlib, signal, shlex, threading, webbrowser, csv
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

ENV_NAME = "NB_HCPA_Workflow"

# ---------------------------
# Guardião do ambiente conda
# ---------------------------
def _reexec_in_conda():
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

    os.environ["NB_PIPELINE_BOOTSTRAPPED"] = "1"
    os.execv(conda, ["conda", "run", "-n", ENV_NAME, "python", *sys.argv])

if os.environ.get("NB_PIPELINE_BOOTSTRAPPED") != "1":
    if os.environ.get("CONDA_DEFAULT_ENV") != ENV_NAME:
        try:
            import tkinter  # noqa
        except Exception:
            _reexec_in_conda()
        else:
            _reexec_in_conda()

# ---------------------------
# Pastas
# ---------------------------
BASE_DIR = Path(__file__).resolve().parent
ASSEMBLY_DIR = BASE_DIR / "assembly_output"
ASSEMBLY_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------
# App
# ---------------------------
class AssemblyApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("NB_HCPA — Montagem (SPAdes / Unicycler)")
        try:
            self.attributes('-zoomed', True)
        except Exception:
            self.state('zoomed')

        self.env_name = ENV_NAME
        self.asm_current_proc = None
        self.asm_stop_requested = False

        # Batch state
        self.batch_queue = []         # lista de dicionários (jobs)
        self.batch_running = False
        self.batch_thread = None

        self._build_ui()
        self._check_environment()
        self._check_required_tools(["spades.py", "unicycler"])

    # ---------- Infra ----------
    def activate_env_command(self, command: str) -> str:
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

    def _check_required_tools(self, tools):
        missing = [t for t in tools if not self.tool_exists(t)]
        if missing:
            lista = "\n- ".join(missing)
            msg = (
                f"As seguintes ferramentas não foram encontradas no ambiente "
                f"'{self.env_name}':\n- {lista}\n\n"
                "Instale-as (ex.: mamba/conda install -y -c bioconda -c conda-forge <tool>) e tente novamente."
            )
            self._popup("Ferramentas ausentes", msg)

    def _check_environment(self):
        try:
            result = subprocess.run(
                self.activate_env_command("echo $CONDA_DEFAULT_ENV"),
                shell=True, capture_output=True, text=True, check=True
            )
            if ENV_NAME not in result.stdout:
                raise RuntimeError("Environment not active.")
        except Exception as e:
            self._popup("Aviso de ambiente", f"Não foi possível verificar o ambiente: {e}")

    def _popup(self, title, message):
        popup = tk.Toplevel(self)
        popup.title(title)
        popup.geometry("520x260")
        ttk.Label(popup, text=message, wraplength=480, justify="left").pack(pady=12, padx=12)
        ttk.Button(popup, text="Fechar", command=popup.destroy).pack(pady=8)

    # ---------- UI ----------
    def _build_ui(self):
        main = ttk.Frame(self)
        main.pack(fill="both", expand=True)

        # Top bar
        top = ttk.Frame(main)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="Montagem de genomas — SPAdes / Unicycler").pack(side="left")
        ttk.Button(top, text="Abrir pasta de saídas", command=lambda: webbrowser.open_new_tab(f"file://{ASSEMBLY_DIR.resolve()}")).pack(side="right", padx=6)
        ttk.Button(top, text="?", width=3, command=self._show_help).pack(side="right")

        # Form
        form = ttk.LabelFrame(main, text="Entradas & Parâmetros (job atual)")
        form.pack(fill="x", padx=8, pady=6)
        for c in range(8):
            form.columnconfigure(c, weight=1)

        self.var_tool = tk.StringVar(value="unicycler")   # unicycler|spades
        ttk.Label(form, text="Ferramenta").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        ttk.Combobox(form, textvariable=self.var_tool, state="readonly",
                     values=["unicycler", "spades"], width=14).grid(row=0, column=1, sticky="w")

        self.var_mode = tk.StringVar(value="PE")          # PE|SE
        ttk.Label(form, text="Modo (curtas)").grid(row=0, column=2, sticky="e")
        ttk.Combobox(form, textvariable=self.var_mode, state="readonly",
                     values=["PE", "SE"], width=6).grid(row=0, column=3, sticky="w")

        self.var_threads = tk.IntVar(value=16)
        ttk.Label(form, text="Threads").grid(row=0, column=4, sticky="e")
        ttk.Spinbox(form, from_=1, to=128, textvariable=self.var_threads, width=6).grid(row=0, column=5, sticky="w")

        self.var_sample = tk.StringVar(value="sample1")
        ttk.Label(form, text="Nome da amostra").grid(row=0, column=6, sticky="e")
        ttk.Entry(form, textvariable=self.var_sample, width=18).grid(row=0, column=7, sticky="w")

        ttk.Label(form, text="R1 (curtas)").grid(row=1, column=0, sticky="w")
        self.var_r1 = tk.StringVar(value="")
        ttk.Entry(form, textvariable=self.var_r1).grid(row=1, column=1, columnspan=5, sticky="ew", padx=4)
        ttk.Button(form, text="Escolher…", command=lambda: self._pick(self.var_r1)).grid(row=1, column=6, sticky="w")

        ttk.Label(form, text="R2 (curtas)").grid(row=2, column=0, sticky="w")
        self.var_r2 = tk.StringVar(value="")
        ttk.Entry(form, textvariable=self.var_r2).grid(row=2, column=1, columnspan=5, sticky="ew", padx=4)
        ttk.Button(form, text="Escolher…", command=lambda: self._pick(self.var_r2)).grid(row=2, column=6, sticky="w")

        ttk.Label(form, text="SE (curtas únicas)").grid(row=3, column=0, sticky="w")
        self.var_se = tk.StringVar(value="")
        ttk.Entry(form, textvariable=self.var_se).grid(row=3, column=1, columnspan=5, sticky="ew", padx=4)
        ttk.Button(form, text="Escolher…", command=lambda: self._pick(self.var_se)).grid(row=3, column=6, sticky="w")

        ttk.Label(form, text="Long reads (híbrido)").grid(row=4, column=0, sticky="w")
        self.var_long = tk.StringVar(value="")
        ttk.Entry(form, textvariable=self.var_long).grid(row=4, column=1, columnspan=5, sticky="ew", padx=4)
        ttk.Button(form, text="Escolher…", command=lambda: self._pick(self.var_long)).grid(row=4, column=6, sticky="w")

        # Unicycler opts
        ucf = ttk.LabelFrame(main, text="Opções — Unicycler")
        ucf.pack(fill="x", padx=8, pady=6)
        for c in range(10): ucf.columnconfigure(c, weight=1)

        self.var_uc_mode = tk.StringVar(value="normal")
        ttk.Label(ucf, text="--mode").grid(row=0, column=0, sticky="w")
        ttk.Combobox(ucf, textvariable=self.var_uc_mode, values=["conservative","normal","bold"],
                     state="readonly", width=14).grid(row=0, column=1, sticky="w")

        self.var_keep = tk.IntVar(value=1)
        ttk.Label(ucf, text="--keep").grid(row=0, column=2, sticky="e")
        ttk.Spinbox(ucf, from_=0, to=3, textvariable=self.var_keep, width=6).grid(row=0, column=3, sticky="w")

        self.var_min_fasta_len = tk.IntVar(value=100)
        ttk.Label(ucf, text="--min_fasta_length").grid(row=0, column=4, sticky="e")
        ttk.Spinbox(ucf, from_=0, to=100000, increment=50,
                    textvariable=self.var_min_fasta_len, width=8).grid(row=0, column=5, sticky="w")

        self.var_linear = tk.IntVar(value=0)
        ttk.Label(ucf, text="--linear_seqs").grid(row=0, column=6, sticky="e")
        ttk.Spinbox(ucf, from_=0, to=10, textvariable=self.var_linear, width=6).grid(row=0, column=7, sticky="w")

        # SPAdes opts
        spf = ttk.LabelFrame(main, text="Opções — SPAdes")
        spf.pack(fill="x", padx=8, pady=6)
        for c in range(10): spf.columnconfigure(c, weight=1)

        self.var_sp_careful = tk.BooleanVar(value=True)
        ttk.Checkbutton(spf, text="--careful (reduz erros estruturais; mais lento)",
                        variable=self.var_sp_careful).grid(row=0, column=0, columnspan=3, sticky="w")
        self.var_sp_kmers = tk.StringVar(value="")
        ttk.Label(spf, text="--kmers (vazio = automático)").grid(row=0, column=3, sticky="e")
        ttk.Entry(spf, textvariable=self.var_sp_kmers, width=24).grid(row=0, column=4, sticky="w")

        # Ações single
        btns = ttk.Frame(main)
        btns.pack(fill="x", padx=8, pady=4)
        ttk.Button(btns, text="Rodar montagem (job atual)", command=self._run_assembly_thread).pack(side="left")
        ttk.Button(btns, text="Interromper", command=self._stop_assembly).pack(side="left", padx=6)

        # --------- Fila (batch) ----------
        batch = ttk.LabelFrame(main, text="Fila de Montagens (batch)")
        batch.pack(fill="both", expand=False, padx=8, pady=6)
        batch.columnconfigure(0, weight=1)
        batch.rowconfigure(0, weight=1)

        self.batch_list = tk.Listbox(batch, height=8, selectmode="extended")
        self.batch_list.grid(row=0, column=0, sticky="nsew")
        sbatch = ttk.Scrollbar(batch, orient="vertical", command=self.batch_list.yview)
        sbatch.grid(row=0, column=1, sticky="ns")
        self.batch_list.configure(yscrollcommand=sbatch.set)

        bbtns = ttk.Frame(batch)
        bbtns.grid(row=1, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Button(bbtns, text="Adicionar job atual à fila", command=self._batch_add_current).pack(side="left")
        ttk.Button(bbtns, text="Remover selecionado(s)", command=self._batch_remove_selected).pack(side="left", padx=6)
        ttk.Button(bbtns, text="Carregar CSV…", command=self._batch_load_csv).pack(side="left", padx=6)
        ttk.Button(bbtns, text="Salvar CSV…", command=self._batch_save_csv).pack(side="left", padx=6)
        ttk.Button(bbtns, text="Limpar fila", command=self._batch_clear).pack(side="left", padx=6)
        ttk.Button(bbtns, text="Executar fila", command=self._batch_run_thread).pack(side="left", padx=6)
        ttk.Button(bbtns, text="Parar fila", command=self._batch_stop).pack(side="left", padx=6)

        # Log
        self.txt = tk.Text(main, wrap="word", height=16)
        self.txt.pack(fill="both", expand=True, padx=8, pady=6)

        # Saídas
        lf = ttk.LabelFrame(main, text="Saídas (assembly_output)")
        lf.pack(fill="both", expand=False, padx=8, pady=6)
        lf.columnconfigure(0, weight=1)
        lf.rowconfigure(0, weight=1)

        self.lb = tk.Listbox(lf, height=8, selectmode="extended")
        self.lb.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.lb.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.lb.configure(yscrollcommand=sb.set)

        btns2 = ttk.Frame(lf)
        btns2.grid(row=1, column=0, columnspan=2, sticky="ew", pady=6)
        ttk.Button(btns2, text="Abrir selecionado(s)", command=self._open_selected).pack(side="left")
        ttk.Button(btns2, text="Abrir pasta de saídas", command=lambda: webbrowser.open_new_tab(f"file://{ASSEMBLY_DIR.resolve()}")).pack(side="left", padx=6)

        self._update_outputs()

    # ---------- Helpers UI ----------
    def _pick(self, var: tk.StringVar):
        p = filedialog.askopenfilename()
        if p:
            var.set(p)

    def _append_log(self, s: str):
        self.txt.insert("end", s)
        self.txt.see("end")
        self.txt.update_idletasks()

    # ---------- Single run ----------
    def _run_assembly_thread(self):
        def target():
            try:
                self._run_job(self._collect_current_job())
            finally:
                pass
        threading.Thread(target=target, daemon=True).start()

    def _collect_current_job(self):
        # Monta um dict com todos os parâmetros atuais
        return {
            "sample": (self.var_sample.get() or "sample1").strip(),
            "tool": self.var_tool.get(),
            "mode": self.var_mode.get().upper(),
            "r1": self.var_r1.get().strip(),
            "r2": self.var_r2.get().strip(),
            "se": self.var_se.get().strip(),
            "long": self.var_long.get().strip(),
            "threads": int(self.var_threads.get()),
            "uc_mode": self.var_uc_mode.get(),
            "keep": int(self.var_keep.get()),
            "min_fasta_length": int(self.var_min_fasta_len.get()),
            "linear_seqs": int(self.var_linear.get()),
            "spades_careful": bool(self.var_sp_careful.get()),
            "spades_kmers": self.var_sp_kmers.get().strip(),
        }

    def _run_job(self, job):
        # Validações
        tool = job["tool"]
        mode = job["mode"]
        r1, r2, se, longr = job["r1"], job["r2"], job["se"], job["long"]

        if tool == "spades":
            if mode == "PE" and (not r1 or not r2):
                self._append_log(f"[{job['sample']}] ERRO: SPAdes (PE) requer R1 e R2.\n")
                return
            if mode == "SE" and not se:
                self._append_log(f"[{job['sample']}] ERRO: SPAdes (SE) requer SE.\n")
                return
        else:
            if mode == "PE" and (not r1 or not r2) and not se and not longr:
                self._append_log(f"[{job['sample']}] ERRO: Unicycler requer R1+R2 e/ou SE; long reads opcionais.\n")
                return
            if mode == "SE" and not se and not longr:
                self._append_log(f"[{job['sample']}] ERRO: Unicycler (SE) requer SE ou long reads.\n")
                return

        outdir = (ASSEMBLY_DIR / job["sample"]).resolve()
        outdir.mkdir(parents=True, exist_ok=True)

        # Monta comando
        if tool == "spades":
            parts = ["spades.py", "-t", str(job["threads"]), "-o", str(outdir)]
            if job["spades_careful"]:
                parts += ["--careful"]
            if job["spades_kmers"]:
                parts += ["--kmers", job["spades_kmers"]]
            if mode == "PE":
                parts += ["-1", r1, "-2", r2]
            else:
                parts += ["-s", se]
            cmd = self.activate_env_command(" ".join(shlex.quote(p) for p in parts))
            self._append_log(f"[{job['sample']}] [SPAdes] {cmd}\n")
        else:
            parts = ["unicycler", "-o", str(outdir), "-t", str(job["threads"]),
                     "--mode", job["uc_mode"],
                     "--keep", str(job["keep"]),
                     "--min_fasta_length", str(job["min_fasta_length"]),
                     "--linear_seqs", str(job["linear_seqs"])]
            if r1 and r2:
                parts += ["-1", r1, "-2", r2]
            if se:
                parts += ["-s", se]
            if longr:
                parts += ["-l", longr]
            cmd = self.activate_env_command(" ".join(shlex.quote(p) for p in parts))
            self._append_log(f"[{job['sample']}] [Unicycler] {cmd}\n")

        # Executa & streama
        ret = self._run_and_stream(cmd, prefix=f"[{job['sample']}] ")
        if ret == 0:
            self._append_log(f"[{job['sample']}] Montagem concluída.\n")
        else:
            self._append_log(f"[{job['sample']}] Montagem finalizada com código {ret}.\n")
        self._update_outputs()

    def _run_and_stream(self, cmd: str, prefix: str = "") -> int:
        self.asm_stop_requested = False
        try:
            self.asm_current_proc = subprocess.Popen(
                cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                preexec_fn=os.setsid if hasattr(os, "setsid") else None, bufsize=1
            )
            for line in iter(self.asm_current_proc.stdout.readline, ""):
                if line:
                    self._append_log(prefix + line)
                if self.asm_stop_requested and self.asm_current_proc and self.asm_current_proc.poll() is None:
                    try:
                        if hasattr(os, "setsid"):
                            os.killpg(os.getpgid(self.asm_current_proc.pid), signal.SIGTERM)
                        else:
                            self.asm_current_proc.terminate()
                    except Exception:
                        pass
                    self._append_log(prefix + "[Interrompido pelo usuário]\n")
                    break
            ret = self.asm_current_proc.wait()
            self.asm_current_proc = None
            return ret
        except Exception as e:
            self._append_log(prefix + f"Erro inesperado: {e}\n")
            return -1

    def _stop_assembly(self):
        self.asm_stop_requested = True
        if self.asm_current_proc and self.asm_current_proc.poll() is None:
            try:
                if hasattr(os, "setsid"):
                    os.killpg(os.getpgid(self.asm_current_proc.pid), signal.SIGTERM)
                else:
                    self.asm_current_proc.terminate()
            except Exception:
                pass

    # ---------- Batch/Fila ----------
    def _batch_add_current(self):
        job = self._collect_current_job()
        self.batch_queue.append(job)
        self.batch_list.insert("end", self._job_label(job))

    def _batch_remove_selected(self):
        sel = list(self.batch_list.curselection())
        if not sel:
            return
        for idx in reversed(sel):
            self.batch_list.delete(idx)
            del self.batch_queue[idx]

    def _batch_clear(self):
        self.batch_queue.clear()
        self.batch_list.delete(0, "end")

    def _job_label(self, job):
        tool = job["tool"]
        mode = job["mode"]
        lr = " +long" if bool(job["long"]) else ""
        return f"{job['sample']} — {tool} [{mode}{lr}] threads={job['threads']}"

    def _batch_load_csv(self):
        path = filedialog.askopenfilename(filetypes=[("CSV", "*.csv"), ("All", "*.*")])
        if not path:
            return
        loaded = 0
        with open(path, newline="") as fh:
            rd = csv.DictReader(fh)
            # Se não tiver cabeçalho, tentar ler como lista simples
            if rd.fieldnames is None:
                self._append_log("[batch] CSV sem cabeçalho não suportado — adicione cabeçalho.\n")
                return
            for row in rd:
                job = {
                    "sample": (row.get("sample") or "sample1").strip(),
                    "tool": (row.get("tool") or "unicycler").strip(),
                    "mode": (row.get("mode") or "PE").strip().upper(),
                    "r1": (row.get("r1") or "").strip(),
                    "r2": (row.get("r2") or "").strip(),
                    "se": (row.get("se") or "").strip(),
                    "long": (row.get("long") or "").strip(),
                    "threads": int(row.get("threads") or 16),
                    "uc_mode": (row.get("uc_mode") or "normal").strip(),
                    "keep": int(row.get("keep") or 1),
                    "min_fasta_length": int(row.get("min_fasta_length") or 100),
                    "linear_seqs": int(row.get("linear_seqs") or 0),
                    "spades_careful": (str(row.get("spades_careful") or "1").lower() in ("1","true","yes","y")),
                    "spades_kmers": (row.get("spades_kmers") or "").strip(),
                }
                self.batch_queue.append(job)
                self.batch_list.insert("end", self._job_label(job))
                loaded += 1
        self._append_log(f"[batch] {loaded} job(s) carregado(s) de {path}\n")

    def _batch_save_csv(self):
        if not self.batch_queue:
            messagebox.showinfo("Fila vazia", "Não há jobs para salvar.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        fields = ["sample","tool","mode","r1","r2","se","long","threads","uc_mode","keep",
                  "min_fasta_length","linear_seqs","spades_careful","spades_kmers"]
        with open(path, "w", newline="") as fh:
            wr = csv.DictWriter(fh, fieldnames=fields)
            wr.writeheader()
            for job in self.batch_queue:
                wr.writerow(job)
        self._append_log(f"[batch] Fila salva em {path}\n")

    def _batch_run_thread(self):
        if self.batch_running:
            messagebox.showwarning("Fila", "A fila já está em execução.")
            return
        if not self.batch_queue:
            messagebox.showinfo("Fila", "A fila está vazia.")
            return
        self.batch_running = True
        self._append_log("[batch] Iniciando execução sequencial da fila…\n")
        def target():
            try:
                for idx, job in enumerate(list(self.batch_queue)):
                    if not self.batch_running:
                        break
                    self._append_log(f"[batch] ({idx+1}/{len(self.batch_queue)}) {self._job_label(job)}\n")
                    self._run_job(job)
                    if not self.batch_running:
                        break
                if self.batch_running:
                    self._append_log("[batch] Fila concluída.\n")
            finally:
                self.batch_running = False
        self.batch_thread = threading.Thread(target=target, daemon=True)
        self.batch_thread.start()

    def _batch_stop(self):
        if self.batch_running:
            self._append_log("[batch] Solicitando parada da fila…\n")
            self.batch_running = False
            self._stop_assembly()  # interrompe o job atual

    # ---------- Saídas ----------
    def _update_outputs(self):
        self.lb.delete(0, "end")
        if ASSEMBLY_DIR.exists():
            for f in sorted(ASSEMBLY_DIR.rglob("assembly.fasta")):
                self.lb.insert("end", str(f))
            for f in sorted(ASSEMBLY_DIR.rglob("assembly.gfa")):
                self.lb.insert("end", str(f))
            for f in sorted(ASSEMBLY_DIR.rglob("unicycler.log")):
                self.lb.insert("end", str(f))
            for f in sorted(ASSEMBLY_DIR.rglob("spades.log")):
                self.lb.insert("end", str(f))

    def _open_selected(self):
        sel = self.lb.curselection()
        if not sel:
            messagebox.showwarning("Aviso", "Nenhum item selecionado.")
            return
        for i in sel:
            p = self.lb.get(i)
            webbrowser.open_new_tab(f"file://{Path(p).resolve()}")

    # ---------- Ajuda ----------
    def _show_help(self):
        help_text = (
            "Montagem (SPAdes / Unicycler)\n\n"
            "Ferramenta:\n"
            " • unicycler: pipeline p/ genomas bacterianos; aceita curtas (Illumina), longas (Nanopore/PacBio) ou híbrido.\n"
            " • spades: montador p/ leituras curtas (SE/PE).\n\n"
            "Modo (curtas): PE (R1+R2) ou SE (um FASTQ).\n\n"
            "Arquivos:\n"
            " • R1/R2: curtas pareadas; SE: curtas únicas; Long: long reads p/ híbrido (Unicycler).\n\n"
            "Unicycler:\n"
            " • --mode: conservative|normal|bold — trade-off entre segurança e completude.\n"
            " • --keep 0..3: retenção de intermediários (2 acelera troca de modo).\n"
            " • --min_fasta_length N: oculta contigs muito curtas no FASTA (GFA mantém).\n"
            " • --linear_seqs N: nº esperado de sequências lineares (geralmente 0).\n\n"
            "SPAdes:\n"
            " • --careful: reduz misassemblies; mais lento.\n"
            " • --kmers: ex. 21,33,55,77,99 (vazio = automático).\n\n"
            "Batch/Fila:\n"
            " • Adicionar job atual à fila: usa os parâmetros preenchidos acima.\n"
            " • CSV (cabeçalho): sample,tool,mode,r1,r2,se,long,threads,uc_mode,keep,min_fasta_length,linear_seqs,spades_careful,spades_kmers\n"
            "   - tool: unicycler|spades; mode: PE|SE; spades_careful: 1/0/true/false.\n"
            " • Executar fila: roda sequencialmente (1 por vez) com log prefixado por [sample].\n"
            " • Parar fila: interrompe o job atual e cancela o restante.\n"
        )
        win = tk.Toplevel(self)
        win.title("Ajuda — Montagem")
        win.geometry("840x600")
        txt = tk.Text(win, wrap="word")
        txt.insert("1.0", help_text)
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        sb = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
        sb.pack(side="right", fill="y")
        txt.configure(yscrollcommand=sb.set)

# ---------------------------
# Main
# ---------------------------
if __name__ == "__main__":
    app = AssemblyApp()
    app.mainloop()
