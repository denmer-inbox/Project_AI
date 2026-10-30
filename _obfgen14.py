
import ast, builtins, io, keyword, string
SRC = r"C:\Users\nickd\Downloads\Project_AI\opencode_provider_manager.py"
DST = r"C:\Users\nickd\Downloads\Project_AI\opencode_provider_manager.obfuscated.py"
tree = ast.parse(io.open(SRC, encoding="utf-8").read())
for node in ast.walk(tree):
    if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        if (node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)):
            if len(node.body) == 1: node.body[0] = ast.Pass()
            else: node.body.pop(0)
R = set(dir(builtins)) | set(keyword.kwlist) | {"self","cls","__name__","__main__","__file__","__init__","__doc__","__spec__","__package__","__loader__","__build_class__","annotations"}
for node in ast.walk(tree):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        for a in node.names:
            R.add((a.asname or a.name).split(".")[0]); R.add(a.name.split(".")[0])
tops = [n.name for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))]
def gs(n):
    alph = string.ascii_lowercase + string.digits
    s, m = "", n
    while True:
        s = alph[m % len(alph)] + s
        m = m // len(alph) - 1
        if m < 0: break
    return "_" + s
mp, seq = {}, 0
for name in tops:
    if name in R or name in {"App","main"} or name.startswith("__"): continue
    seq += 1; mp[name] = gs(seq)
class RG(ast.NodeTransformer):
    def visit_FunctionDef(self, node):
        if node.name in mp: node.name = mp[node.name]
        self.generic_visit(node); return node
    def visit_ClassDef(self, node):
        if node.name in mp: node.name = mp[node.name]
        self.generic_visit(node); return node
    def visit_Name(self, node):
        if node.id in mp: node.id = mp[node.id]
        return node
io.open(DST,"w",encoding="utf-8",newline="").write(ast.unparse(RG().visit(tree)))
print("obf ok")
