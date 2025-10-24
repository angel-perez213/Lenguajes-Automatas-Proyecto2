from __future__ import annotations
import re
import os
import subprocess
import shutil
from dataclasses import dataclass, field
from typing import List, Tuple, Dict, Set, Optional

# ===== 1) LÉXICO =====
Token = Tuple[str, str, int, int]

KEYWORDS = {"class", "int", "void", "return"}
SYMBOLS = {
    "{" : "LBRACE", "}" : "RBRACE", "(" : "LPAREN", ")" : "RPAREN",
    ";" : "SEMI", "," : "COMMA"
}
OPERATORS = {
    "+" : "PLUS", "-" : "MINUS", "*" : "STAR", "/" : "SLASH",
    "<" : "LT", ">" : "GT", "==" : "EQEQ", "=" : "EQ"
}

RE_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
RE_NUM = re.compile(r"[0-9]+")

def tokenize(source: str) -> Tuple[List[Token], List[str]]:
    i = 0; line = 1; col = 1
    tokens: List[Token] = []
    errors: List[str] = []

    def advance(n: int = 1):
        nonlocal i, line, col
        for _ in range(n):
            if i < len(source):
                if source[i] == "\n":
                    line += 1; col = 1
                else:
                    col += 1
                i += 1

    while i < len(source):
        ch = source[i]
        if ch.isspace():
            advance(); continue

        if ch == "/" and i + 1 < len(source) and source[i+1] == "/":
            while i < len(source) and source[i] != "\n":
                advance()
            continue
        if ch == "/" and i + 1 < len(source) and source[i+1] == "*":
            advance(2)
            start_line, start_col = line, col
            closed = False
            while i < len(source):
                if source[i] == "*" and i + 1 < len(source) and source[i+1] == "/":
                    advance(2); closed = True; break
                else:
                    advance()
            if not closed:
                errors.append(f"Comentario de bloque no cerrado iniciado en {start_line}:{start_col}")
            continue

        if i + 1 < len(source) and source[i:i+2] == "==":
            tokens.append(("EQEQ", "==", line, col)); advance(2); continue

        if ch in SYMBOLS:
            tokens.append((SYMBOLS[ch], ch, line, col)); advance(); continue
        if ch in "+-*/<>=" and not (ch == "=" and i+1 < len(source) and source[i+1] == "="):
            tokens.append((OPERATORS[ch], ch, line, col)); advance(); continue

        m_id = RE_ID.match(source, i)
        if m_id:
            lex = m_id.group(0)
            ttype = lex if lex in KEYWORDS else "id"
            tokens.append((ttype, lex, line, col))
            advance(len(lex)); continue

        m_num = RE_NUM.match(source, i)
        if m_num:
            lex = m_num.group(0)
            tokens.append(("number", lex, line, col))
            advance(len(lex)); continue

        errors.append(f"Carácter ilegal '{ch}' en {line}:{col}")
        advance()

    tokens.append(("$", "$", line, col))
    return tokens, errors

# ===== 2) GRAMÁTICA Y LL(1) =====
Grammar: Dict[str, List[Tuple[str, ...]]] = {
    "Prog"      : [("ClassDecl",)],
    "ClassDecl" : [("class", "id", "{", "MemberList", "}")],
    "MemberList": [("Member", "MemberList"), tuple()],
    "Member"    : [("MethodDecl",), ("VarDecl",)],
    "VarDecl"   : [("Type", "id", ";")],
    "MethodDecl": [("Type", "id", "(", "ParamList", ")", "Block")],
    "ParamList" : [("Param", "ParamRest"), tuple()],
    "ParamRest" : [(",", "Param", "ParamRest"), tuple()],
    "Param"     : [("Type", "id")],
    "Block"     : [("{", "StmtList", "}")],
    "StmtList"  : [("Stmt", "StmtList"), tuple()],
    "Stmt"      : [("VarDecl",), ("Assign",), ("Return",), ("Call", ";")],
    "Assign"    : [("id", "=", "Expr", ";")],
    "Return"    : [("return", "Expr", ";")],
    "Call"      : [("id", "(", "ArgList", ")")],
    "ArgList"   : [("Expr", "ArgRest"), tuple()],
    "ArgRest"   : [(",", "Expr", "ArgRest"), tuple()],
    "Expr"      : [("Add", "RelP")],
    "RelP"      : [("<", "Add", "RelP"), (">", "Add", "RelP"), ("==", "Add", "RelP"), tuple()],
    "Add"       : [("Term", "AddP")],
    "AddP"      : [("+", "Term", "AddP"), ("-", "Term", "AddP"), tuple()],
    "Term"      : [("Factor", "TermP")],
    "TermP"     : [("*", "Factor", "TermP"), ("/", "Factor", "TermP"), tuple()],
    "Factor"    : [("id",), ("number",), ("(", "Expr", ")")],
    "Type"      : [("int",), ("void",)]
}
NONTERMS = list(Grammar.keys())
TERMS: Set[str] = set()
for A, prods in Grammar.items():
    for p in prods:
        for s in p:
            if s and s not in Grammar:
                TERMS.add(s)
TERMS.add("$")
EPSILON = tuple()

def first_of_seq(seq: Tuple[str, ...], FIRST: Dict[str, Set[str]]) -> Set[str]:
    out: Set[str] = set()
    if seq == EPSILON:
        out.add("ε"); return out
    for sym in seq:
        if sym in Grammar:
            out |= (FIRST[sym] - {"ε"})
            if "ε" in FIRST[sym]:
                continue
            else:
                return out
        else:
            out.add(sym); return out
    out.add("ε")
    return out

def compute_FIRST() -> Dict[str, Set[str]]:
    FIRST: Dict[str, Set[str]] = {A: set() for A in Grammar}
    changed = True
    while changed:
        changed = False
        for A, prods in Grammar.items():
            before = len(FIRST[A])
            for p in prods:
                FIRST[A] |= first_of_seq(p, FIRST)
            if len(FIRST[A]) != before:
                changed = True
    return FIRST

def compute_FOLLOW(FIRST: Dict[str, Set[str]]) -> Dict[str, Set[str]]:
    FOLLOW: Dict[str, Set[str]] = {A: set() for A in Grammar}
    FOLLOW["Prog"].add("$")
    changed = True
    while changed:
        changed = False
        for A, prods in Grammar.items():
            for p in prods:
                for i, B in enumerate(p):
                    if B in Grammar:
                        beta = p[i+1:]
                        first_beta = first_of_seq(beta, FIRST)
                        before = len(FOLLOW[B])
                        FOLLOW[B] |= (first_beta - {"ε"})
                        if "ε" in first_beta or len(beta) == 0:
                            FOLLOW[B] |= FOLLOW[A]
                        if len(FOLLOW[B]) != before:
                            changed = True
    return FOLLOW

Table: Dict[Tuple[str, str], Tuple[str, ...]] = {}
Conflicts: List[str] = []
def build_table(FIRST: Dict[str, Set[str]], FOLLOW: Dict[str, Set[str]]):
    global Table, Conflicts
    Table = {}; Conflicts = []
    for A, prods in Grammar.items():
        for p in prods:
            first_p = first_of_seq(p, FIRST)
            for a in (first_p - {"ε"}):
                key = (A, a)
                if key in Table and Table[key] != p:
                    Conflicts.append(f"Conflicto LL(1) en M[{A},{a}] entre {Table[key]} y {p}")
                Table[key] = p
            if "ε" in first_p:
                for b in FOLLOW[A]:
                    key = (A, b)
                    if key in Table and Table[key] != p:
                        Conflicts.append(f"Conflicto LL(1) en M[{A},{b}] entre {Table[key]} y {p}")
                    Table[key] = p

# ===== 3) PARSER PREDICTIVO =====
@dataclass
class Node:
    label: str
    children: List["Node"] = field(default_factory=list)
    token: Optional[Token] = None

    def add(self, child: "Node"):
        self.children.append(child)

    def to_dot(self) -> str:
        lines = ["digraph G {", "  node [shape=box];"]
        counter = 0
        id_map: Dict[int, str] = {}
        def escape(s: str) -> str:
            return s.replace("\\", "\\\\").replace('"', '\\"')
        def emit(n: "Node") -> str:
            nonlocal counter
            nid = id(n)
            if nid not in id_map:
                name = f"n{counter}"; counter += 1
                label = n.label
                if n.token is not None:
                    ttype, lex, ln, co = n.token
                    label = f"{label}\\n{lex} (@{ln}:{co})"
                label = escape(label)
                lines.append(f'  {name} [label="{label}"];')
                id_map[nid] = name
            return id_map[nid]
        def walk(n: "Node"):
            src = emit(n)
            for c in n.children:
                dst = emit(c)
                lines.append(f"  {src} -> {dst};")
                walk(c)
        walk(self)
        lines.append("}")
        return "\n".join(lines)

@dataclass
class ParseResult:
    root: Optional[Node]
    errors: List[str]
    variables: List[str]
    methods: List[str]

def parse(tokens: List[Token]) -> ParseResult:
    stack: List[Tuple[str, Optional[Node]]] = [("$", None), ("Prog", None)]
    cursor = 0
    errors: List[str] = []
    root: Optional[Node] = None
    variables: List[str] = []
    methods: List[str] = []
    def look() -> Token:
        return tokens[cursor]
    while stack:
        X, parent = stack.pop()
        ttype, lex, ln, co = look()
        if X == "$":
            if ttype != "$":
                errors.append(f"Se esperaba fin de entrada, pero quedó '{lex}' en {ln}:{co}")
            break
        if X in Grammar:
            prod = None
            key = (X, ttype) if ttype in TERMS else (X, lex)
            if ttype in KEYWORDS or ttype in {
                "$", "id", "number", "LPAREN", "RPAREN", "LBRACE", "RBRACE",
                "SEMI", "COMMA", "PLUS", "MINUS", "STAR", "SLASH", "EQ", "EQEQ", "LT", "GT"
            }:
                term_map = {
                    "LPAREN": "(", "RPAREN": ")", "LBRACE": "{", "RBRACE": "}",
                    "SEMI": ";", "COMMA": ",", "PLUS": "+", "MINUS": "-",
                    "STAR": "*", "SLASH": "/", "EQ": "=", "LT": "<", "GT": ">",
                    "EQEQ": "=="
                }
                a = lex if ttype in KEYWORDS else term_map.get(ttype, ttype)
                prod = Table.get((X, a)) or Table.get((X, ttype))
            else:
                prod = Table.get((X, ttype)) or Table.get((X, lex))
            cur_node = Node(X)
            if parent is None:
                if root is None:
                    root = cur_node
            else:
                parent.add(cur_node)
            if prod is None:
                errors.append(f"Error sintáctico en {ln}:{co}: no hay producción para {X} con lookahead '{lex}'")
                if ttype == "$":
                    break
                else:
                    cur_node.add(Node(f"<error: inesperado {lex}>", token=look()))
                    cursor += 1
                continue
            if prod != EPSILON:
                for sym in reversed(prod):
                    stack.append((sym, cur_node))
            else:
                cur_node.add(Node("ε"))
            if X == "VarDecl":
                j = cursor
                while j < len(tokens) and tokens[j][0] != "id" and tokens[j][0] != "$":
                    j += 1
                if j < len(tokens) and tokens[j][0] == "id":
                    variables.append(tokens[j][1])
            if X == "MethodDecl":
                j = cursor; saw_id = None
                while j < len(tokens) and tokens[j][0] != "$":
                    if tokens[j][0] == "id":
                        saw_id = tokens[j][1]; break
                    j += 1
                if saw_id:
                    methods.append(saw_id)
        else:
            expected = X
            rev_map = {
                "(": "LPAREN", ")": "RPAREN", "{": "LBRACE", "}": "RBRACE",
                ";": "SEMI", ",": "COMMA", "+": "PLUS", "-": "MINUS",
                "*": "STAR", "/": "SLASH", "=": "EQ", "<": "LT", ">": "GT",
                "==": "EQEQ"
            }
            match_ok = False
            leaf_label = expected
            if expected in {"id", "number", "$", "class", "int", "void", "return"}:
                if expected in KEYWORDS or expected in {"$", "id", "number"}:
                    if (expected in KEYWORDS and lex == expected) or (expected == ttype) or (expected == "$" and ttype == "$"):
                        match_ok = True
                else:
                    match_ok = (expected == ttype)
            elif expected in rev_map:
                match_ok = (ttype == rev_map[expected])
            else:
                match_ok = (expected == ttype or expected == lex)
            leaf = Node(leaf_label, token=look())
            if parent is not None:
                parent.add(leaf)
            if match_ok:
                cursor += 1
            else:
                errors.append(f"Token inesperado en {ln}:{co}: se esperaba '{expected}' y llegó '{lex}'")
                if parent is not None:
                    parent.add(Node(f"<insertado {expected}>"))
                cursor += 1 if ttype != "$" else 0
    return ParseResult(root=root, errors=errors, variables=variables, methods=methods)

# ===== 4) SALIDAS =====
def write_table(path: str):
    lines = ["TABLA LL(1) - entradas M[A,a] con A no terminal y a terminal", ""]
    for (A, a), p in sorted(Table.items()):
        rhs = " ".join(p) if p else "ε"
        lines.append(f"M[{A},{a}] = {rhs}")
    if Conflicts:
        lines += ["", "Conflictos detectados:", *Conflicts]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def write_errors(path: str, lex_errors: List[str], parse_errors: List[str]):
    lines = ["ERRORES LÉXICOS Y SINTÁCTICOS"]
    if not lex_errors and not parse_errors:
        lines.append("Sin errores.")
    if lex_errors:
        lines += ["", "- Léxicos:", *lex_errors]
    if parse_errors:
        lines += ["", "- Sintácticos:", *parse_errors]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def write_dot(path: str, root: Optional[Node]):
    content = "digraph G {\n  label=\"Arbol vacio\";\n}" if root is None else root.to_dot()
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)

def write_ast_dot(path: str, root: Optional[Node]):
    write_dot(path, root)

# ===== 5) GUI (Tkinter + visor DOT) =====
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Intentamos usar Pillow (mejor zoom). Si no está, se desactiva zoom suave.
try:
    from PIL import Image, ImageTk  # pip install pillow
    PIL_OK = True
except Exception:
    PIL_OK = False
    Image = None
    ImageTk = None

class App(ttk.Frame):
    def __init__(self, master: tk.Tk):
        super().__init__(master, padding=16)
        self.pack(fill="both", expand=True)
        master.title("Analizador LL(1) - Subconjunto Java")
        master.geometry("1100x720")
        master.minsize(980, 600)

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#f9fafb")
        style.configure("TLabel", background="#f9fafb", foreground="#111318")
        style.configure("TButton", padding=8)
        style.configure("Header.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Sub.TLabel", font=("Segoe UI", 10), foreground="#6b7280")

        self.input_path = tk.StringVar()
        self.output_dir = tk.StringVar()
        self.gen_ast = tk.BooleanVar(value=True)

        head = ttk.Frame(self); head.pack(fill="x")
        ttk.Label(head, text="Analizador Sintactico LL(1)", style="Header.TLabel").pack(anchor="w")
        ttk.Label(head, text="Lexer + Tabla LL(1) + Parser + Árbol (.dot) + Reportes + Visor integrado",
                  style="Sub.TLabel").pack(anchor="w", pady=(2, 12))

        body = ttk.Frame(self); body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(1, weight=1)

        left = ttk.Frame(body); left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        ttk.Label(left, text="Archivo de entrada (programa.txt)").pack(anchor="w", pady=(0, 4))
        row1 = ttk.Frame(left); row1.pack(fill="x", pady=(0, 8))
        ttk.Entry(row1, textvariable=self.input_path).pack(side="left", fill="x", expand=True)
        ttk.Button(row1, text="Buscar...", command=self.pick_input).pack(side="left", padx=(8, 0))

        ttk.Label(left, text="Carpeta de salida").pack(anchor="w", pady=(8, 4))
        row2 = ttk.Frame(left); row2.pack(fill="x")
        ttk.Entry(row2, textvariable=self.output_dir).pack(side="left", fill="x", expand=True)
        ttk.Button(row2, text="Seleccionar...", command=self.pick_output).pack(side="left", padx=(8, 0))

        btns = ttk.Frame(left); btns.pack(fill="x", pady=12)
        ttk.Button(btns, text="Analizar", command=self.run_all).pack(side="left")
        ttk.Button(btns, text="Limpiar", command=self.clear_views).pack(side="left", padx=8)

        box = ttk.LabelFrame(left, text="Árbol y reportes", padding=8)
        box.pack(fill="x", pady=(0, 12))
        info = (
            "• Árbol de derivación (.dot) y visor integrado.\n"
            "• Reportes: errores.txt, tabla_transicion.txt.\n"
            "• Exporta imagen con Graphviz: dot -Tpng arbol.dot -o arbol.png"
        )
        ttk.Label(box, text=info, justify="left").pack(anchor="w")
        ttk.Checkbutton(box, text="Generar AST (ast.dot)", variable=self.gen_ast).pack(anchor="w", pady=(6, 0))

        self.summary = tk.Text(left, height=12, wrap="word")
        self.summary.pack(fill="both", expand=True, pady=(8, 0))
        self.summary.insert("end", "Selecciona un archivo de entrada y una carpeta de salida.\nHaz clic en Analizar.")
        self.summary.configure(state="disabled")

        right = ttk.Notebook(body); right.grid(row=0, column=1, rowspan=2, sticky="nsew")

        self.tab_tokens = tk.Text(right, wrap="none"); right.add(self.tab_tokens, text="Tokens")
        self.tab_errors = tk.Text(right, wrap="word"); right.add(self.tab_errors, text="Errores")
        self.tab_table = tk.Text(right, wrap="none"); right.add(self.tab_table, text="Tabla LL(1)")

        # --- Visor del árbol ---
        self.tab_view = ttk.Frame(right)
        right.add(self.tab_view, text="Árbol (vista)")

        # Canvas + scrollbars
        self.canvas = tk.Canvas(self.tab_view, bg="white")
        hbar = ttk.Scrollbar(self.tab_view, orient="horizontal", command=self.canvas.xview)
        vbar = ttk.Scrollbar(self.tab_view, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        self.tab_view.rowconfigure(0, weight=1)
        self.tab_view.columnconfigure(0, weight=1)

        # Barra de controles
        controls = ttk.Frame(self.tab_view); controls.grid(row=2, column=0, sticky="ew", pady=(6,0))
        ttk.Button(controls, text="Zoom -", command=lambda: self.zoom_step(0.9)).pack(side="left")
        ttk.Button(controls, text="Zoom +", command=lambda: self.zoom_step(1.1)).pack(side="left", padx=6)
        ttk.Button(controls, text="Ajustar a ventana", command=self.fit_to_window).pack(side="left")
        ttk.Button(controls, text="Abrir PNG", command=self.open_png_external).pack(side="left", padx=6)

        # Estado del visor
        self.img_pil = None           # PIL.Image
        self.img_tk = None            # ImageTk.PhotoImage o tk.PhotoImage
        self.img_path = None          # ruta a arbol.png
        self.zoom = 1.0

        # Pan con arrastre
        self.canvas.bind("<ButtonPress-1>", self._start_pan)
        self.canvas.bind("<B1-Motion>", self._do_pan)

        # Zoom con rueda (Windows/Mac/Linux)
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)       # Windows/macOS
        self.canvas.bind("<Button-4>", lambda e: self.zoom_step(1.1))  # Linux scroll up
        self.canvas.bind("<Button-5>", lambda e: self.zoom_step(0.9))  # Linux scroll down

    # ------ Helpers de visor ------
    def _start_pan(self, event):
        self.canvas.scan_mark(event.x, event.y)

    def _do_pan(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _on_mousewheel(self, event):
        factor = 1.1 if event.delta > 0 else 0.9
        self.zoom_step(factor, focus=(self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)))

    def zoom_step(self, factor: float, focus: Optional[Tuple[float,float]] = None):
        if not self.img_path:
            return
        new_zoom = max(0.1, min(5.0, self.zoom * factor))
        if abs(new_zoom - self.zoom) < 1e-3:
            return
        self.zoom = new_zoom
        self._show_image(focus_center=focus)

    def fit_to_window(self):
        if not self.img_path:
            return
        bbox = self.canvas.bbox("all")
        if self.img_pil:
            w, h = self.img_pil.size
        else:
            # sin PIL intentamos leer tamaño desde bbox
            if bbox:
                w = bbox[2] - bbox[0]
                h = bbox[3] - bbox[1]
            else:
                return
        cw = max(1, self.canvas.winfo_width())
        ch = max(1, self.canvas.winfo_height())
        scale = min(cw / w, ch / h)
        self.zoom = max(0.1, min(5.0, scale))
        self._show_image()

    def open_png_external(self):
        if not self.img_path:
            return
        try:
            if os.name == "nt":
                os.startfile(self.img_path)  # type: ignore
            elif sys.platform == "darwin":
                subprocess.Popen(["open", self.img_path])
            else:
                subprocess.Popen(["xdg-open", self.img_path])
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir la imagen:\n{e}")

    def render_and_show(self, dot_path: str, out_dir: str):
        """Usa 'dot' para generar PNG y lo muestra en el canvas."""
        dot_bin = shutil.which("dot")
        if not dot_bin:
            messagebox.showwarning(
                "Graphviz no encontrado",
                "No se encontró 'dot' en PATH.\nInstala Graphviz o añade su carpeta 'bin' al PATH."
            )
            return
        png_path = os.path.join(out_dir, "arbol.png")
        try:
            subprocess.run([dot_bin, "-Tpng", dot_path, "-o", png_path, "-Gdpi=150"],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            messagebox.showerror("Graphviz", f"Error al renderizar DOT:\n{e.stderr.decode('utf-8','ignore')}")
            return

        self.img_path = png_path
        # Carga imagen original
        self.img_pil = None
        if PIL_OK:
            try:
                self.img_pil = Image.open(self.img_path)
            except Exception:
                self.img_pil = None

        self.zoom = 1.0
        self._show_image()

    def _show_image(self, focus_center: Optional[Tuple[float,float]] = None):
        self.canvas.delete("all")
        if self.img_pil and PIL_OK:
            w0, h0 = self.img_pil.size
            w = max(1, int(w0 * self.zoom))
            h = max(1, int(h0 * self.zoom))
            try:
                img_resized = self.img_pil.resize((w, h), Image.LANCZOS)
            except Exception:
                img_resized = self.img_pil.resize((w, h))
            self.img_tk = ImageTk.PhotoImage(img_resized)
        else:
            # Fallback sin PIL: intentamos PhotoImage directo (puede no soportar PNG en algunos Tk)
            try:
                self.img_tk = tk.PhotoImage(file=self.img_path)
            except Exception:
                messagebox.showwarning(
                    "Vista limitada",
                    "No se pudo cargar PNG en Tk sin Pillow. Instala 'pillow' para habilitar el visor (pip install pillow)."
                )
                return

        img_id = self.canvas.create_image(0, 0, image=self.img_tk, anchor="nw", tags=("img",))
        self.canvas.config(scrollregion=(0, 0, self.img_tk.width(), self.img_tk.height()))

        # Centrar o respetar foco de zoom
        if focus_center:
            fx, fy = focus_center
            self.canvas.xview_moveto(max(0, (fx - self.canvas.winfo_width()/2) / max(1, self.img_tk.width())))
            self.canvas.yview_moveto(max(0, (fy - self.canvas.winfo_height()/2) / max(1, self.img_tk.height())))
        else:
            # centrar al cargar
            cw = self.canvas.winfo_width(); ch = self.canvas.winfo_height()
            ox = max(0, (self.img_tk.width() - cw) / 2)
            oy = max(0, (self.img_tk.height() - ch) / 2)
            if self.img_tk.width() > 0:
                self.canvas.xview_moveto(ox / self.img_tk.width())
            if self.img_tk.height() > 0:
                self.canvas.yview_moveto(oy / self.img_tk.height())

    # ------ UI base ------
    def pick_input(self):
        path = filedialog.askopenfilename(
            title="Selecciona programa.txt",
            filetypes=[("Texto", "*.txt"), ("Todos", "*.*")]
        )
        if path:
            self.input_path.set(path)

    def pick_output(self):
        path = filedialog.askdirectory(title="Selecciona carpeta de salida")
        if path:
            self.output_dir.set(path)

    def clear_views(self):
        for w in (self.tab_tokens, self.tab_errors, self.tab_table, self.summary):
            w.configure(state="normal"); w.delete("1.0", "end")
        self.summary.insert("end", "Listo. Carga un archivo y presiona Analizar.")
        for w in (self.tab_tokens, self.tab_errors, self.tab_table, self.summary):
            w.configure(state="disabled")
        self.canvas.delete("all"); self.img_path = None; self.img_pil = None; self.img_tk = None

    def run_all(self):
        in_path = self.input_path.get().strip()
        out_dir = self.output_dir.get().strip()
        if not in_path or not os.path.isfile(in_path):
            messagebox.showerror("Falta archivo", "Selecciona un archivo de entrada válido (programa.txt)")
            return
        if not out_dir or not os.path.isdir(out_dir):
            messagebox.showerror("Falta carpeta", "Selecciona una carpeta de salida válida")
            return

        src = open(in_path, "r", encoding="utf-8").read()
        tokens, lex_errors = tokenize(src)
        FIRST = compute_FIRST(); FOLLOW = compute_FOLLOW(FIRST); build_table(FIRST, FOLLOW)
        result = parse(tokens)

        tabla_path = os.path.join(out_dir, "tabla_transicion.txt")
        errs_path = os.path.join(out_dir, "errores.txt")
        arbol_path = os.path.join(out_dir, "arbol.dot")
        ast_path = os.path.join(out_dir, "ast.dot")

        write_table(tabla_path)
        write_errors(errs_path, lex_errors, result.errors)
        write_dot(arbol_path, result.root)
        if self.gen_ast.get():
            write_ast_dot(ast_path, result.root)

        # Mostrar en pestañas
        self.tab_tokens.configure(state="normal"); self.tab_tokens.delete("1.0", "end")
        self.tab_errors.configure(state="normal"); self.tab_errors.delete("1.0", "end")
        self.tab_table.configure(state="normal"); self.tab_table.delete("1.0", "end")
        self.summary.configure(state="normal"); self.summary.delete("1.0", "end")

        self.tab_tokens.insert("end", f"Total tokens: {len(tokens)}\n\n")
        for t in tokens:
            self.tab_tokens.insert("end", f"{t[0]:<10}  {t[1]:<12}  @ {t[2]}:{t[3]}\n")

        if not lex_errors and not result.errors:
            self.tab_errors.insert("end", "Sin errores lexicos ni sintacticos.\n")
        else:
            if lex_errors:
                self.tab_errors.insert("end", "- Lexicos:\n" + "\n".join(lex_errors) + "\n\n")
            if result.errors:
                self.tab_errors.insert("end", "- Sintacticos:\n" + "\n".join(result.errors) + "\n")

        if Conflicts:
            self.tab_table.insert("end", "Conflictos LL(1) detectados:\n" + "\n".join(Conflicts) + "\n\n")
        for (A, a), p in sorted(Table.items()):
            rhs = " ".join(p) if p else "ε"
            self.tab_table.insert("end", f"M[{A},{a}] = {rhs}\n")

        num_lines = src.count("\n") + 1
        self.summary.insert("end", f"Lineas procesadas: {num_lines}\n")
        self.summary.insert("end", f"Variables detectadas: {len(result.variables)} — {', '.join(result.variables) if result.variables else '-'}\n")
        self.summary.insert("end", f"Metodos detectados: {len(result.methods)} — {', '.join(result.methods) if result.methods else '-'}\n")
        self.summary.insert("end", "Archivos generados en: " + out_dir + "\n  - errores.txt\n  - tabla_transicion.txt\n  - arbol.dot\n")
        if self.gen_ast.get():
            self.summary.insert("end", "  - ast.dot\n")

        for w in (self.tab_tokens, self.tab_errors, self.tab_table, self.summary):
            w.configure(state="disabled")

        # Renderizar y mostrar en el visor integrado
        self.render_and_show(arbol_path, out_dir)

        messagebox.showinfo("Listo", "Análisis completado. Árbol renderizado en la pestaña 'Árbol (vista)'.")

def main():
    root = tk.Tk()
    App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
